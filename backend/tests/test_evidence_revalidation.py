"""Frozen EvidenceSets are revalidated; the snapshot is not mutated."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    EvidenceSetItem,
    EvidenceSetRevalidation,
    Kund,
    TextUnitRecord,
)
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.execution import (
    add_evidence_items,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
    get_evidence_set,
)
from app.services.knowledge.claims import (
    KnowledgeClaim,
    answer_research_need,
    knowledge_claim_id,
    persist_knowledge_claim,
)
from app.services.knowledge.events import CLAIM_ADDED, list_graph_events
from app.services.knowledge.revalidation import (
    REVALIDATION_CLEAR,
    REVALIDATION_IMPACTED,
    RevalidationError,
    revalidate_after_event,
)
from app.services.research import research_evidence
from app.services.research.knowledge_question import research_question_key

QUESTION = "Jämkades villkoret enligt 36 §?"


class _ImpactJev:
    def __init__(self, noul: float) -> None:
        self.noul = noul
        self.calls = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        del state, questions, model, timeout_seconds
        self.calls += 1
        return JevSystemOneResult(
            answers={"material_change": {"noul": self.noul}},
            model="jev-test",
            latency_ms=1.0,
            input_chars=1,
            usage=JevUsage(),
            raw={},
        )


class _FailingJev:
    async def ask(self, *, state, questions, model, timeout_seconds):
        del state, questions, model, timeout_seconds
        raise JevClientError("jev down", category="transport")


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _setup_frozen_set(session: AsyncSession, *, excerpt: str = "old holding"):
    kund = Kund(name="acme", slug="acme-rev", available_modules=["dd"])
    session.add(kund)
    await session.flush()
    session.add(
        CanonicalDocumentRecord(
            id="doc-a",
            customer_id=kund.id,
            source_type="upload",
            canonical_uri="doc://a",
            title="A",
            extra={},
        )
    )
    session.add(
        DocumentVersionRecord(
            id="ver-a",
            document_id="doc-a",
            content_hash="hash",
            mime_type="text/plain",
            extra={},
        )
    )
    session.add(
        TextUnitRecord(
            id="tu-hold",
            document_version_id="ver-a",
            document_id="doc-a",
            section_id=None,
            ordinal=0,
            text="HD ansåg X",
            content_hash="tu-hold",
        )
    )
    session.add(
        TextUnitRecord(
            id="tu-other",
            document_version_id="ver-a",
            document_id="doc-a",
            section_id=None,
            ordinal=1,
            text="Irrelevant passage",
            content_hash="tu-other",
        )
    )
    await session.flush()
    run = await create_run(
        session,
        customer_id=kund.id,
        module="dd",
        title="Jämkning",
        context={"case_id": "case-1"},
    )
    evidence_set = await create_evidence_set(session, run_id=run.id)
    await add_evidence_items(
        session,
        evidence_set_id=evidence_set.id,
        items=[
            research_evidence(
                research_need_id="need-1",
                source_type="swedish_case_law",
                status="found",
                excerpt=excerpt,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                metadata={
                    "answered_by_question_key": research_question_key(QUESTION),
                    "knowledge_claim_ids": ["prior-claim"],
                    "text_unit_ids": ["tu-hold"],
                },
            )
        ],
    )
    frozen = await freeze_evidence_set(session, evidence_set.id)
    return kund, frozen


async def _new_claim(session: AsyncSession, customer_id: int) -> str:
    value: dict[str, object] = {"value": False}
    claim = KnowledgeClaim(
        id=knowledge_claim_id(
            document_version_id="ver-a",
            predicate="legal.adjustment_granted",
            value=value,
        ),
        customer_id=customer_id,
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="legal.adjustment_granted",
        value=value,
        supporting_text_unit_ids=("tu-hold",),
    )
    await persist_knowledge_claim(session, claim)
    await answer_research_need(
        session,
        research_need_id="need-2",
        question_key=research_question_key(QUESTION),
        claim_ids=[claim.id],
        source_type="swedish_case_law",
    )
    return claim.id


@pytest.mark.asyncio
async def test_jev_impact_marks_frozen_set_without_mutating_items(db):
    kund, frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    before = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    gate = _ImpactJev(0.81)
    decisions = await revalidate_after_event(db, added.id, jev=gate)
    after = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    reloaded = await get_evidence_set(db, frozen.id)
    rows = list((await db.execute(select(EvidenceSetRevalidation))).scalars().all())
    assert gate.calls == 1
    assert [item.state for item in decisions] == [REVALIDATION_IMPACTED]
    assert decisions[0].evidence_set_id == frozen.id
    assert [row.state for row in rows] == [REVALIDATION_IMPACTED]
    assert reloaded.status == "frozen"
    assert reloaded.graph_revision_at_freeze == reloaded.frozen_at
    assert [item.excerpt for item in before] == [item.excerpt for item in after]


@pytest.mark.asyncio
async def test_low_impact_is_clear_and_unrelated_claim_skips_jev(db):
    kund, frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    clear_gate = _ImpactJev(0.12)
    decisions = await revalidate_after_event(db, added.id, jev=clear_gate)
    assert [item.state for item in decisions] == [REVALIDATION_CLEAR]
    assert decisions[0].evidence_set_id == frozen.id

    other = KnowledgeClaim(
        id=knowledge_claim_id(
            document_version_id="ver-a",
            predicate="other.topic",
            value={"value": "nope"},
        ),
        customer_id=kund.id,
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="other.topic",
        value={"value": "nope"},
        supporting_text_unit_ids=("tu-other",),
    )
    await persist_knowledge_claim(db, other)
    await answer_research_need(
        db,
        research_need_id="need-other",
        question_key=research_question_key("Helt annan fråga?"),
        claim_ids=[other.id],
        source_type="swedish_case_law",
    )
    other_events = await list_graph_events(
        db, customer_id=kund.id, node_kind="claim", node_id=other.id
    )
    unused = _ImpactJev(0.99)
    assert await revalidate_after_event(db, other_events[0].id, jev=unused) == []
    assert unused.calls == 0


@pytest.mark.asyncio
async def test_jev_failure_does_not_invent_clear(db):
    kund, _frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    with pytest.raises(JevClientError):
        await revalidate_after_event(db, added.id, jev=_FailingJev())
    assert list((await db.execute(select(EvidenceSetRevalidation))).scalars().all()) == []
    with pytest.raises(RevalidationError, match="missing"):
        await revalidate_after_event(db, "missing-event", jev=_ImpactJev(0.9))
