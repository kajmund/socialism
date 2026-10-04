from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    ExecutionRun,
    KnowledgeQuestionEvidenceLink,
    KnowledgeQuestionRow,
    Kund,
)
from app.services.execution.service import (
    attach_evidence_set,
    create_attempt,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
    mark_ready,
)
from app.services.expert_chat_evidence import (
    evidence_tool_handler_for_chat,
    reusable_expert_chat_evidence_context,
)
from app.services.expert_memory_schedule import memory_tasks, schedule_expert_memory_update
from app.services.research.knowledge_question import identity_from_text, tenant_question_scope


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _store_answer(
    session: AsyncSession,
    *,
    customer_id: int,
    question: str,
    case_id: str | None = None,
    frozen: bool = True,
) -> None:
    run = await create_run(
        session,
        customer_id=customer_id,
        module="expertgranskning",
        title=question,
        context={},
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="research_question",
        configuration_snapshot={},
        input_snapshot={},
    )
    evidence_set = await create_evidence_set(
        session,
        run_id=run.id,
        created_from_attempt_id=attempt.id,
    )
    await attach_evidence_set(
        session,
        attempt_id=attempt.id,
        evidence_set_id=evidence_set.id,
    )
    if frozen:
        await freeze_evidence_set(session, evidence_set.id)
        await mark_ready(session, attempt.id)
    identity = identity_from_text(question)
    row = KnowledgeQuestionRow(
        id=f"question-{customer_id}-{case_id or 'general'}",
        identity_key=identity.identity_key,
        normalized_text=identity.normalized_text,
        display_text=identity.display_text,
        namespace=tenant_question_scope(customer_id).namespace,
        visibility="tenant",
        customer_id=customer_id,
    )
    session.add(row)
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        KnowledgeQuestionEvidenceLink(
            id=f"link-{customer_id}-{case_id or 'general'}",
            question_id=row.id,
            evidence_ref=f"ref-{customer_id}-{case_id or 'general'}",
            relation="ANSWERED_BY",
            title="Avtalslagen 36 §",
            excerpt="Avtalsvillkor får jämkas om villkoret är oskäligt.",
            locator="36 §",
            source_type="swedish_law",
            provider="test",
            provenance={"knowledge_case_id": case_id} if case_id else {},
            retrieved_at=now,
            observed_at=now,
            freshness="fresh",
            visibility="tenant",
            source_attempt_id=attempt.id,
        )
    )
    await session.flush()


def _prompts() -> dict[str, str]:
    return {"chat.expert.research_evidence": "FRYST EVIDENS\n{evidence}"}


async def test_legacy_evidence_link_is_not_read_by_expert_chat(session):
    customer = Kund(name="Acme", slug="acme", available_modules=[])
    session.add(customer)
    await session.flush()
    question = "Vilka rekvisit gäller för jämkning enligt 36 § avtalslagen?"
    await _store_answer(session, customer_id=customer.id, question=question)

    before = await session.scalar(select(func.count()).select_from(ExecutionRun))
    await session.commit()
    context = await reusable_expert_chat_evidence_context(
        session,
        customer_id=customer.id,
        question=question,
        prompts=_prompts(),
    )

    assert context == ""
    after = await session.scalar(select(func.count()).select_from(ExecutionRun))
    assert after == before


async def test_chat_reuse_is_tenant_isolated_and_excludes_case_evidence(session):
    first = Kund(name="First", slug="first", available_modules=[])
    second = Kund(name="Second", slug="second", available_modules=[])
    session.add_all([first, second])
    await session.flush()
    question = "Vilka rekvisit gäller för jämkning?"
    await _store_answer(session, customer_id=first.id, question=question)
    await _store_answer(
        session,
        customer_id=second.id,
        question=question,
        case_id="document-1",
    )

    await session.commit()
    isolated = await reusable_expert_chat_evidence_context(
        session,
        customer_id=second.id,
        question=question,
        prompts=_prompts(),
    )

    assert isolated == ""


async def test_non_matching_question_returns_no_context(session):
    customer = Kund(name="Acme", slug="acme", available_modules=[])
    session.add(customer)
    await session.flush()
    await _store_answer(
        session,
        customer_id=customer.id,
        question="Vilka rekvisit gäller för jämkning?",
    )

    await session.commit()
    context = await reusable_expert_chat_evidence_context(
        session,
        customer_id=customer.id,
        question="Hur fungerar en konkurrensklausul?",
        prompts=_prompts(),
    )

    assert context == ""


async def test_unfrozen_evidence_is_not_exposed_to_chat(session):
    customer = Kund(name="Acme", slug="acme", available_modules=[])
    session.add(customer)
    await session.flush()
    question = "Vilka rekvisit gäller för jämkning?"
    await _store_answer(
        session,
        customer_id=customer.id,
        question=question,
        frozen=False,
    )

    await session.commit()
    context = await reusable_expert_chat_evidence_context(
        session,
        customer_id=customer.id,
        question=question,
        prompts=_prompts(),
    )

    assert context == ""


@pytest.mark.asyncio
async def test_evidence_tool_returns_lookup_text(monkeypatch):
    async def rendered(*_args, **kwargs):
        assert kwargs["question"] == "förvärv"
        assert kwargs["assume_caller_idle"] is False
        return "FRYST EVIDENS"

    monkeypatch.setattr(
        "app.services.expert_chat_evidence.reusable_expert_chat_evidence_context",
        rendered,
    )
    handle = evidence_tool_handler_for_chat(None, customer_id=1, prompts={})

    assert await handle({"question": "förvärv"}) == "FRYST EVIDENS"


@pytest.mark.asyncio
async def test_evidence_tool_reports_a_miss(monkeypatch):
    async def empty(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(
        "app.services.expert_chat_evidence.reusable_expert_chat_evidence_context",
        empty,
    )
    handle = evidence_tool_handler_for_chat(None, customer_id=1, prompts={})

    assert await handle({"question": "hej"}) == (
        "Ingen tidigare fryst researchevidens matchar frågan."
    )


@pytest.mark.asyncio
async def test_evidence_tool_requires_a_question():
    handle = evidence_tool_handler_for_chat(None, customer_id=1, prompts={})

    with pytest.raises(ValueError, match="lookup_research_evidence"):
        await handle({"question": "  "})


@pytest.mark.asyncio
async def test_memory_update_is_scheduled_without_waiting(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    class Memory:
        async def add_chat_turn(self, **_kwargs):
            started.set()
            await release.wait()

    monkeypatch.setattr(
        "app.services.expert_memory_schedule.get_expert_memory",
        lambda: Memory(),
    )
    persona = SimpleNamespace(kind="expert", customer_id=1, id="exp_1_jurist", name="Josef")
    schedule_expert_memory_update(persona, message="hej", reply="hej själv", image_sha256=None)

    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()
    pending = [task for task in memory_tasks if not task.done()]
    if pending:
        await asyncio.gather(*pending)
