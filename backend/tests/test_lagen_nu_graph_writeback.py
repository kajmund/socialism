"""lagen.nu graph writes wait until every document is interpreted."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.services.knowledge.answer_review import AnswerReviewDecision
from app.database.base import Base
from app.database.models import Kund
from app.services.lagen_nu import graph_writeback as writeback
from app.services.lagen_nu.graph_writeback import (
    GraphWritebackQueue,
    PendingGraphWrite,
    persist_pending_graph_writes,
)
from tests.test_lagen_nu_document_fetch import _law_source, _two_doc_client
from tests.test_lagen_nu_provider import FakeLegalInterpreter
from tests.test_research import _context, _need


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Kund(id=7, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db
    await engine.dispose()


def test_queue_take_empties_pending_writes():
    queue = GraphWritebackQueue()
    item = PendingGraphWrite(
        review_decision=AnswerReviewDecision("never"),
        claims=(),
        entities=(),
        edges=(),
        research_need_id="research_1",
        question="Vad gäller?",
        source_type="swedish_law",
        customer_id=7,
    )
    queue.enqueue(item)
    assert queue.take() == [item]
    assert queue.take() == []


@pytest.mark.asyncio
async def test_persist_rejects_mixed_customer_ids():
    with pytest.raises(ValueError, match="customer_id"):
        await persist_pending_graph_writes(
            None,  # type: ignore[arg-type]
            [
                PendingGraphWrite(
                    review_decision=AnswerReviewDecision("never"),
                    claims=(),
                    entities=(),
                    edges=(),
                    research_need_id="research_1",
                    question="a",
                    source_type="swedish_law",
                    customer_id=7,
                ),
                PendingGraphWrite(
                    review_decision=AnswerReviewDecision("never"),
                    claims=(),
                    entities=(),
                    edges=(),
                    research_need_id="research_1",
                    question="b",
                    source_type="swedish_law",
                    customer_id=8,
                ),
            ],
        )


@pytest.mark.asyncio
async def test_graph_writeback_waits_until_every_document_is_interpreted(
    session: AsyncSession, monkeypatch
):
    events: list[str] = []
    original_interpret = FakeLegalInterpreter.interpret
    original_persist = writeback.persist_knowledge_claims

    async def tracking_interpret(self, **kwargs):
        events.append("interpret")
        return await original_interpret(self, **kwargs)

    async def tracking_persist(db, claims):
        events.append("persist")
        return await original_persist(db, claims)

    monkeypatch.setattr(FakeLegalInterpreter, "interpret", tracking_interpret)
    monkeypatch.setattr(writeback, "persist_knowledge_claims", tracking_persist)
    evidence = await _law_source(session, _two_doc_client()).research(
        _need("swedish_law", question="preskription av fordran"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert events == ["interpret", "interpret", "persist", "persist"]


@pytest.mark.asyncio
async def test_cancelled_research_drops_deferred_writes(session: AsyncSession, monkeypatch):
    original_interpret = FakeLegalInterpreter.interpret
    calls = 0

    async def cancel_on_second(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError
        return await original_interpret(self, **kwargs)

    monkeypatch.setattr(FakeLegalInterpreter, "interpret", cancel_on_second)
    source = _law_source(session, _two_doc_client())
    with pytest.raises(asyncio.CancelledError):
        await source.research(
            _need("swedish_law", question="preskription av fordran"),
            _context(),
        )
    assert source._graph_writes.take() == []
