from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund, ResearchQuestion, ResearchQuestionExpert
from app.services.execution import create_attempt, create_run
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    add_question_dependency,
    create_general_question,
    create_specific_question,
)
from app.services.research.question_execution import (
    ExecutableResearchQuestion,
    QuestionDagExecutionResult,
    QuestionFollowUpDraft,
    QuestionResearchOutcome,
    execute_research_question_dag,
    requeue_interrupted_research_questions,
)


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
            text="Vad innebär klausul 2?",
            context={"clause": "2"},
            origin_kind="expertgranskning",
        )
        await session.commit()
        return attempt.id, specific.id


async def _question(
    factory,
    *,
    attempt_id: str,
    specific_id: str,
    text: str,
    expert: str | None = "avtalsjurist",
):
    async with factory() as session:
        row = await create_general_question(
            session,
            attempt_id=attempt_id,
            specific_question_id=specific_id,
            draft=GeneralQuestionDraft(
                question=text,
                assigned_expert_id=expert,
                raised_by_expert_ids=[expert] if expert else [],
            ),
        )
        await session.commit()
        return row.id


class RecordingWorker:
    def __init__(self, outcomes=None, failures=None):
        self.outcomes = outcomes or {}
        self.failures = failures or set()
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def research_question(
        self, question: ExecutableResearchQuestion
    ) -> QuestionResearchOutcome:
        self.calls.append(question.question)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if question.question in self.failures:
            raise RuntimeError("provider failed")
        return self.outcomes.get(question.question, QuestionResearchOutcome())


async def test_requeue_makes_interrupted_running_question_runnable(factory):
    attempt_id, specific_id = await _setup(factory)
    question_id = await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Vilka rekvisit gäller?",
    )
    async with factory() as session:
        row = await session.get(ResearchQuestion, question_id)
        assert row is not None
        row.status = "running"
        await session.commit()

    async with factory() as session:
        count = await requeue_interrupted_research_questions(session, attempt_id=attempt_id)
        await session.commit()
    assert count == 1

    worker = RecordingWorker()
    result = await execute_research_question_dag(factory, attempt_id=attempt_id, worker=worker)
    assert result.status == "completed"
    assert worker.calls == ["Vilka rekvisit gäller?"]


async def test_empty_question_graph_is_not_reported_as_completed_research(factory):
    attempt_id, _specific_id = await _setup(factory)

    result = await execute_research_question_dag(
        factory,
        attempt_id=attempt_id,
        worker=RecordingWorker(),
    )

    assert result.status == "not_needed"
    assert result.completed_count == 0
    assert result.waves == 0


async def test_independent_questions_run_in_bounded_parallel(factory):
    attempt_id, specific_id = await _setup(factory)
    for text in ("Fråga A?", "Fråga B?", "Fråga C?"):
        await _question(
            factory,
            attempt_id=attempt_id,
            specific_id=specific_id,
            text=text,
        )
    worker = RecordingWorker()
    result = await execute_research_question_dag(
        factory, attempt_id=attempt_id, worker=worker, concurrency=2
    )
    assert result == QuestionDagExecutionResult(
        attempt_id=attempt_id,
        status="completed",
        completed_count=3,
        failed_count=0,
        blocked_count=0,
        waiting_for_assignment_count=0,
        waves=1,
    )
    assert worker.max_active == 2


async def test_dependency_runs_in_later_wave(factory):
    attempt_id, specific_id = await _setup(factory)
    first_id = await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Är avtalslagen tillämplig?",
    )
    second_id = await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Kan avtalet jämkas?",
    )
    async with factory() as session:
        await add_question_dependency(
            session,
            question_id=second_id,
            depends_on_question_id=first_id,
        )
        await session.commit()
    worker = RecordingWorker()
    result = await execute_research_question_dag(factory, attempt_id=attempt_id, worker=worker)
    assert result.waves == 2
    assert worker.calls == ["Är avtalslagen tillämplig?", "Kan avtalet jämkas?"]


async def test_evidence_follow_up_inherits_expert_and_runs_next(factory):
    attempt_id, specific_id = await _setup(factory)
    await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Vilka rekvisit gäller?",
    )
    worker = RecordingWorker(
        outcomes={
            "Vilka rekvisit gäller?": QuestionResearchOutcome(
                follow_ups=(
                    QuestionFollowUpDraft(
                        question="Hur har rekvisitet tillämpats i praxis?",
                        why_needed="Evidensen visar att praxis måste avgränsas.",
                    ),
                )
            )
        }
    )
    result = await execute_research_question_dag(factory, attempt_id=attempt_id, worker=worker)
    assert result.waves == 2
    assert worker.calls == [
        "Vilka rekvisit gäller?",
        "Hur har rekvisitet tillämpats i praxis?",
    ]
    async with factory() as session:
        questions = list(
            (
                await session.execute(
                    select(ResearchQuestion).where(ResearchQuestion.attempt_id == attempt_id)
                )
            ).scalars()
        )
        child = next(row for row in questions if row.origin == "derived")
        experts = list(
            (
                await session.execute(
                    select(ResearchQuestionExpert).where(
                        ResearchQuestionExpert.question_id == child.id
                    )
                )
            ).scalars()
        )
    assert {(row.expert_id, row.role) for row in experts} == {
        ("avtalsjurist", "raised_by"),
        ("avtalsjurist", "assigned_to"),
    }


async def test_unassigned_question_pauses_without_calling_worker(factory):
    attempt_id, specific_id = await _setup(factory)
    await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Vilken skatterättslig fråga uppstår?",
        expert=None,
    )
    worker = RecordingWorker()
    result = await execute_research_question_dag(factory, attempt_id=attempt_id, worker=worker)
    assert result.status == "waiting_for_assignment"
    assert result.waiting_for_assignment_count == 1
    assert worker.calls == []


async def test_worker_failure_is_persisted_without_stopping_independent_questions(factory):
    attempt_id, specific_id = await _setup(factory)
    question_id = await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Vilka rekvisit gäller?",
    )
    worker = RecordingWorker(failures={"Vilka rekvisit gäller?"})
    await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Vilken praxis finns?",
    )
    result = await execute_research_question_dag(factory, attempt_id=attempt_id, worker=worker)
    assert result.status == "completed_with_gaps"
    assert result.completed_count == 1
    assert result.failed_count == 1
    assert set(worker.calls) == {"Vilka rekvisit gäller?", "Vilken praxis finns?"}
    async with factory() as session:
        row = await session.get(ResearchQuestion, question_id)
        assert row is not None
        assert row.status == "failed"
        assert row.outcome_reason == "provider failed"


async def test_failed_dependency_blocks_only_its_dependent_branch(factory):
    attempt_id, specific_id = await _setup(factory)
    parent_id = await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Vilka rekvisit gäller?",
    )
    child_id = await _question(
        factory,
        attempt_id=attempt_id,
        specific_id=specific_id,
        text="Hur tillämpas rekvisiten?",
    )
    async with factory() as session:
        await add_question_dependency(
            session,
            question_id=child_id,
            depends_on_question_id=parent_id,
        )
        await session.commit()

    worker = RecordingWorker(failures={"Vilka rekvisit gäller?"})
    result = await execute_research_question_dag(factory, attempt_id=attempt_id, worker=worker)

    assert result.status == "completed_with_gaps"
    assert result.failed_count == 1
    assert result.blocked_count == 1
    assert worker.calls == ["Vilka rekvisit gäller?"]
