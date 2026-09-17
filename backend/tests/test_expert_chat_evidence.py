from __future__ import annotations

from datetime import UTC, datetime

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
from app.services.expert_chat_evidence import reusable_expert_chat_evidence_context
from app.services.research.knowledge_question import identity_from_text


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
        namespace=f"tenant:{customer_id}",
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


async def test_exact_question_reads_tenant_evidence_without_creating_execution(session):
    customer = Kund(name="Acme", slug="acme", available_modules=[])
    session.add(customer)
    await session.flush()
    question = "Vilka rekvisit gäller för jämkning enligt 36 § avtalslagen?"
    await _store_answer(session, customer_id=customer.id, question=question)

    before = await session.scalar(select(func.count()).select_from(ExecutionRun))
    context = await reusable_expert_chat_evidence_context(
        session,
        customer_id=customer.id,
        question=question,
        prompts=_prompts(),
    )

    assert "FRYST EVIDENS" in context
    assert "[R1] Avtalslagen 36 §" in context
    assert "Avtalsvillkor får jämkas" in context
    assert "Aktualitet: unknown" in context
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

    context = await reusable_expert_chat_evidence_context(
        session,
        customer_id=customer.id,
        question=question,
        prompts=_prompts(),
    )

    assert context == ""
