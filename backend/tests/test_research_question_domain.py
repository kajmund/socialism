from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    KnowledgeQuestionRow,
    Kund,
    ResearchQuestion,
    ResearchQuestionDependency,
    ResearchQuestionExpert,
)
from app.services.execution import create_attempt, create_run
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    ResearchQuestionDomainError,
    add_question_dependency,
    assign_question_expert,
    create_general_question,
    create_specific_question,
    materialize_runtime_needs_as_questions,
)


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


async def _setup(session: AsyncSession):
    customer = Kund(name="Acme", slug="acme", available_modules=["expertgranskning"])
    session.add(customer)
    await session.flush()
    run = await create_run(
        session,
        customer_id=customer.id,
        module="expertgranskning",
        title="Avtalsgranskning",
        context={},
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={},
        input_snapshot={},
    )
    specific = await create_specific_question(
        session,
        run_id=run.id,
        text="Vad innebär klausul 2 i det här avtalet?",
        context={"clause": "2"},
        origin_kind="expertgranskning",
        origin_ref="panel-1",
    )
    return customer, run, attempt, specific


async def test_general_question_is_canonical_and_tracks_expert_lineage(session):
    _customer, _run, attempt, specific = await _setup(session)
    first = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(
            question="Vilka rekvisit gäller för jämkning enligt 36 § avtalslagen?",
            why_needed="Klausulens skälighet måste bedömas.",
            raised_by_expert_ids=["avtalsjurist", "processjurist"],
            assigned_expert_id="avtalsjurist",
        ),
    )
    second = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(
            question="  vilka REKVISIT gäller för jämkning enligt 36 § avtalslagen? ",
            raised_by_expert_ids=["processjurist"],
            assigned_expert_id="avtalsjurist",
        ),
    )
    assert second.id == first.id
    links = list(
        (
            await session.execute(
                select(ResearchQuestionExpert).where(ResearchQuestionExpert.question_id == first.id)
            )
        ).scalars()
    )
    assert {(link.expert_id, link.role) for link in links} == {
        ("avtalsjurist", "raised_by"),
        ("processjurist", "raised_by"),
        ("avtalsjurist", "assigned_to"),
    }


async def test_same_general_question_can_serve_multiple_specific_questions(session):
    _customer, run, attempt, first_specific = await _setup(session)
    second_specific = await create_specific_question(
        session,
        run_id=run.id,
        text="Vad innebär klausul 7 i det här avtalet?",
        context={"clause": "7"},
        origin_kind="expertgranskning",
    )
    draft = GeneralQuestionDraft(
        question="Vilka rekvisit gäller för jämkning enligt 36 § avtalslagen?",
        assigned_expert_id="avtalsjurist",
    )
    first = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=first_specific.id,
        draft=draft,
    )
    second = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=second_specific.id,
        draft=draft,
    )
    assert first.id != second.id
    assert first.knowledge_question_id == second.knowledge_question_id
    canonical = list((await session.execute(select(KnowledgeQuestionRow))).scalars())
    assert len(canonical) == 1


async def test_assignment_is_single_and_unblocks_unassigned_question(session):
    _customer, _run, attempt, specific = await _setup(session)
    question = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(question="Vilken skatterättslig effekt uppstår?"),
    )
    assert question.status == "unassigned"
    await assign_question_expert(session, question_id=question.id, expert_id="skattejurist")
    await assign_question_expert(session, question_id=question.id, expert_id="momsjurist")
    await session.refresh(question)
    assigned = list(
        (
            await session.execute(
                select(ResearchQuestionExpert).where(
                    ResearchQuestionExpert.question_id == question.id,
                    ResearchQuestionExpert.role == "assigned_to",
                )
            )
        ).scalars()
    )
    assert question.status == "pending"
    assert [link.expert_id for link in assigned] == ["momsjurist"]


async def test_dependencies_are_acyclic_and_mark_question_blocked(session):
    _customer, _run, attempt, specific = await _setup(session)
    prerequisite = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(
            question="Är avtalslagen tillämplig?", assigned_expert_id="avtalsjurist"
        ),
    )
    dependent = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(
            question="Kan avtalet jämkas?", assigned_expert_id="avtalsjurist"
        ),
    )
    await add_question_dependency(
        session,
        question_id=dependent.id,
        depends_on_question_id=prerequisite.id,
        reason="Tillämpligheten måste avgöras först.",
    )
    await session.refresh(dependent)
    assert dependent.status == "blocked"
    with pytest.raises(ResearchQuestionDomainError, match="cycle"):
        await add_question_dependency(
            session,
            question_id=prerequisite.id,
            depends_on_question_id=dependent.id,
        )
    edges = list((await session.execute(select(ResearchQuestionDependency))).scalars())
    assert len(edges) == 1


async def test_dependency_cannot_cross_attempts(session):
    _customer, run, first_attempt, specific = await _setup(session)
    second_attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={},
        input_snapshot={},
    )
    first = await create_general_question(
        session,
        attempt_id=first_attempt.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(
            question="Är avtalslagen tillämplig?", assigned_expert_id="avtalsjurist"
        ),
    )
    second = await create_general_question(
        session,
        attempt_id=second_attempt.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(
            question="Kan avtalet jämkas?", assigned_expert_id="avtalsjurist"
        ),
    )
    with pytest.raises(ResearchQuestionDomainError, match="inside one Attempt"):
        await add_question_dependency(
            session,
            question_id=second.id,
            depends_on_question_id=first.id,
        )


async def test_specific_question_cannot_cross_runs(session):
    customer, _run, _attempt, specific = await _setup(session)
    other_run = await create_run(
        session,
        customer_id=customer.id,
        module="expertgranskning",
        title="Annan granskning",
        context={},
    )
    other_attempt = await create_attempt(
        session,
        run_id=other_run.id,
        attempt_type="generic_panel",
        configuration_snapshot={},
        input_snapshot={},
    )
    with pytest.raises(ResearchQuestionDomainError, match="same Run"):
        await create_general_question(
            session,
            attempt_id=other_attempt.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(question="Vilka rekvisit gäller?"),
        )


async def test_runtime_need_bridge_preserves_lineage_and_unassigned_gap(session):
    _customer, _run, attempt, specific = await _setup(session)
    rows = await materialize_runtime_needs_as_questions(
        session,
        attempt_id=attempt.id,
        specific_question_id=specific.id,
        needs=[
            RuntimeResearchNeed(
                research_need_id="need-1",
                question="Vilka rekvisit gäller?",
                why_needed="Bedöm rekvisiten.",
                requested_by=["proposal-1"],
                source_types=["swedish_law"],
            ),
            RuntimeResearchNeed(
                research_need_id="need-2",
                question="Vilken praxis finns?",
                why_needed="Bedöm rättstillämpningen.",
                requested_by=["unknown"],
                source_types=["swedish_law"],
            ),
        ],
        expert_by_requester={"proposal-1": "avtalsjurist"},
    )
    assert [row.runtime_need_id for row in rows] == ["need-1", "need-2"]
    assert [row.status for row in rows] == ["pending", "unassigned"]
    stored = list((await session.execute(select(ResearchQuestion))).scalars())
    assert len(stored) == 2
