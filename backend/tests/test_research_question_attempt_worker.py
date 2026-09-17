from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import EvidenceSet, ExecutionAttempt, Kund, ResearchQuestion
from app.services.execution import create_attempt, create_run
from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.followup import FollowUpNeedDraft
from app.services.research.models import (
    ResearchContext,
    ResearchNeed,
    research_evidence,
)
from app.services.research.planner import FakeResearchPlanner, ResearchNeedDraft
from app.services.research.question_attempt_worker import AttemptResearchQuestionWorker
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from app.services.research.question_execution import execute_research_question_dag
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.router import ResearchRouter


@pytest.fixture
async def factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


async def _setup(factory):
    async with factory() as session:
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
        parent = await create_attempt(
            session,
            run_id=run.id,
            attempt_type="research_question_dag",
            configuration_snapshot={"language": "sv"},
            input_snapshot={},
        )
        specific = await create_specific_question(
            session,
            run_id=run.id,
            text="Vad innebär klausul 2?",
            context={"clause": "2"},
            origin_kind="expertgranskning",
        )
        question = await create_general_question(
            session,
            attempt_id=parent.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(
                question="Vilka rekvisit gäller enligt 36 § avtalslagen?",
                why_needed="Klausulens skälighet ska bedömas.",
                raised_by_expert_ids=["avtalsjurist"],
                assigned_expert_id="avtalsjurist",
            ),
        )
        await session.commit()
        return parent.id, question.id


class FoundSource:
    source_type = "case_knowledge"
    provider_id = "test"

    def __init__(self):
        self.calls = 0

    async def research(self, need: ResearchNeed, context: ResearchContext):
        self.calls += 1
        return [
            research_evidence(
                research_need_id=need.id,
                source_type="case_knowledge",
                status="found",
                title="Avtalet",
                excerpt="Avtalsvillkoret får jämkas om det är oskäligt.",
                locator="s. 2, klausul 2",
                provider="test",
            )
        ]


class IncompleteThenSufficientAssessor:
    def __init__(self):
        self.calls = 0

    async def assess(self, plan, evidence):
        self.calls += 1
        if self.calls == 1:
            return ResearchAssessmentDraft(
                result="insufficient",
                rationale="Praxisfrågan återstår.",
                need_assessments=[
                    ResearchNeedAssessment(
                        research_need_id=plan.needs[0].id,
                        sufficient=False,
                        missing_or_weak="Praxis saknas.",
                    )
                ],
                gaps=["Praxis saknas."],
            )
        return ResearchAssessmentDraft(
            result="sufficient",
            rationale="Både rekvisit och praxis är belagda.",
            need_assessments=[
                ResearchNeedAssessment(
                    research_need_id=need.id,
                    sufficient=True,
                    supporting_evidence_ids=[
                        item.evidence_id for item in evidence if item.research_need_id == need.id
                    ],
                )
                for need in plan.needs
            ],
            considered_evidence_ids=[item.evidence_id for item in evidence],
        )


class OneFollowUpPlanner:
    def __init__(self):
        self.calls = 0

    async def plan_follow_ups(self, **_kwargs):
        self.calls += 1
        return [
            FollowUpNeedDraft(
                question="Hur har rekvisiten tillämpats i praxis?",
                why_needed="Evidensen visar att praxis måste avgränsas.",
                source_types=["case_knowledge"],
                parent_research_need_id="research_1",
            )
        ]


async def test_question_runs_as_child_attempt_with_frozen_evidence(factory):
    parent_id, question_id = await _setup(factory)
    source = FoundSource()

    def router_factory(_session):
        registry = ResearchSourceRegistry()
        registry.register(source)
        return ResearchRouter(registry)

    worker = AttemptResearchQuestionWorker(
        session_factory=factory,
        router_factory=router_factory,
        research_planner=FakeResearchPlanner(
            [
                ResearchNeedDraft(
                    question="Vilka rekvisit framgår av källorna?",
                    why_needed="Rekvisiten måste beläggas.",
                    source_types=["case_knowledge"],
                )
            ]
        ),
    )
    result = await execute_research_question_dag(factory, attempt_id=parent_id, worker=worker)
    assert result.status == "completed"
    async with factory() as session:
        question = await session.get(ResearchQuestion, question_id)
        assert question is not None
        assert question.execution_attempt_id is not None
        child = await session.get(ExecutionAttempt, question.execution_attempt_id)
        assert child is not None
        assert child.parent_attempt_id == parent_id
        assert child.attempt_type == "research_question"
        assert child.status == "ready"
        assert child.input_snapshot["assigned_expert_id"] == "avtalsjurist"
        evidence_set = await session.get(EvidenceSet, child.evidence_set_id)
        assert evidence_set is not None
        assert evidence_set.status == "frozen"
    assert source.calls == 1


async def test_ready_child_attempt_is_reused_without_new_retrieval(factory):
    parent_id, question_id = await _setup(factory)
    source = FoundSource()

    def router_factory(_session):
        registry = ResearchSourceRegistry()
        registry.register(source)
        return ResearchRouter(registry)

    worker = AttemptResearchQuestionWorker(
        session_factory=factory,
        router_factory=router_factory,
        research_planner=FakeResearchPlanner(
            [
                ResearchNeedDraft(
                    question="Vilka rekvisit framgår av källorna?",
                    why_needed="Rekvisiten måste beläggas.",
                    source_types=["case_knowledge"],
                )
            ]
        ),
    )
    await execute_research_question_dag(factory, attempt_id=parent_id, worker=worker)
    async with factory() as session:
        question = await session.get(ResearchQuestion, question_id)
        assert question is not None
        first_child_id = question.execution_attempt_id
        question.status = "pending"
        await session.commit()
    await execute_research_question_dag(factory, attempt_id=parent_id, worker=worker)
    async with factory() as session:
        question = await session.get(ResearchQuestion, question_id)
        children = list(
            (
                await session.execute(
                    select(ExecutionAttempt).where(ExecutionAttempt.parent_attempt_id == parent_id)
                )
            ).scalars()
        )
    assert question is not None
    assert question.execution_attempt_id == first_child_id
    assert len(children) == 1
    assert source.calls == 1


async def test_researched_engine_follow_up_becomes_completed_dag_question(factory):
    parent_id, _question_id = await _setup(factory)
    source = FoundSource()

    def router_factory(_session):
        registry = ResearchSourceRegistry()
        registry.register(source)
        return ResearchRouter(registry)

    worker = AttemptResearchQuestionWorker(
        session_factory=factory,
        router_factory=router_factory,
        research_planner=FakeResearchPlanner(
            [
                ResearchNeedDraft(
                    question="Vilka rekvisit framgår av källorna?",
                    why_needed="Rekvisiten måste beläggas.",
                    source_types=["case_knowledge"],
                )
            ]
        ),
        assessor=IncompleteThenSufficientAssessor(),
        follow_up_planner=OneFollowUpPlanner(),
    )
    result = await execute_research_question_dag(factory, attempt_id=parent_id, worker=worker)
    assert result.status == "completed"
    assert result.completed_count == 2
    async with factory() as session:
        questions = list(
            (
                await session.execute(
                    select(ResearchQuestion).where(ResearchQuestion.attempt_id == parent_id)
                )
            ).scalars()
        )
    parent = next(row for row in questions if row.origin == "initial")
    follow_up = next(row for row in questions if row.origin == "derived")
    assert follow_up.status == "completed"
    assert follow_up.execution_attempt_id == parent.execution_attempt_id
    assert follow_up.runtime_need_id == "followup_1_1"
    assert source.calls == 2
