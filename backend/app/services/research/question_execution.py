"""Dependency-aware execution of expert-owned general research questions."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    KnowledgeQuestionRow,
    ResearchQuestion,
    ResearchQuestionDependency,
    ResearchQuestionExpert,
)
from app.services.execution.service import get_attempt
from app.services.research.progress import ProgressTracker, emit_question_status
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    add_question_dependency,
    create_general_question,
)


class ResearchQuestionExecutionError(RuntimeError):
    """The question DAG cannot make safe forward progress."""


@dataclass(frozen=True)
class ExecutableResearchQuestion:
    id: str
    attempt_id: str
    specific_question_id: str
    knowledge_question_id: str
    question: str
    why_needed: str
    depth: int
    raised_by_expert_ids: tuple[str, ...]
    assigned_expert_id: str


@dataclass(frozen=True)
class QuestionFollowUpDraft:
    """A new question discovered while researching another question."""

    question: str
    why_needed: str
    assigned_expert_id: str | None = None
    raised_by_expert_ids: tuple[str, ...] = ()
    additional_dependency_ids: tuple[str, ...] = ()
    runtime_need_id: str | None = None
    already_researched: bool = False


@dataclass(frozen=True)
class QuestionResearchOutcome:
    follow_ups: tuple[QuestionFollowUpDraft, ...] = ()
    execution_attempt_id: str | None = None


class QuestionResearchWorker(Protocol):
    """Adapter seam for the existing research engine."""

    async def research_question(
        self, question: ExecutableResearchQuestion
    ) -> QuestionResearchOutcome: ...


@dataclass(frozen=True)
class QuestionDagExecutionResult:
    attempt_id: str
    status: str
    completed_count: int
    failed_count: int
    blocked_count: int
    waiting_for_assignment_count: int
    waves: int


@dataclass(frozen=True)
class _QuestionState:
    row: ResearchQuestion
    text: str
    raised_by: tuple[str, ...] = field(default_factory=tuple)
    assigned_to: str | None = None


async def requeue_interrupted_research_questions(
    session: AsyncSession,
    *,
    attempt_id: str,
) -> int:
    """Reset questions left `running` when a worker died mid-wave."""
    questions = list(
        (
            await session.execute(
                select(ResearchQuestion).where(
                    ResearchQuestion.attempt_id == attempt_id,
                    ResearchQuestion.status == "running",
                )
            )
        ).scalars()
    )
    for question in questions:
        question.status = "pending"
        question.outcome_reason = None
    return len(questions)


async def execute_research_question_dag(
    factory: async_sessionmaker[AsyncSession],
    *,
    attempt_id: str,
    worker: QuestionResearchWorker,
    concurrency: int = 4,
) -> QuestionDagExecutionResult:
    """Run dependency-ready questions in bounded parallel waves.

    Worker calls are deliberately outside database transactions. Results are
    persisted at the wave barrier, where follow-up questions become new DAG
    nodes depending on the question whose evidence exposed the gap.
    """
    if concurrency < 1:
        raise ValueError("question concurrency must be >= 1")
    waves = 0
    while True:
        async with factory() as session:
            with ProgressTracker() as progress:
                await get_attempt(session, attempt_id)
                states, dependencies = await _load_graph(session, attempt_id)
                ready = _ready_questions(states, dependencies)
                if not ready:
                    return _terminal_result(attempt_id, states, dependencies, waves)
                for state in ready:
                    state.row.status = "running"
                    await emit_question_status(
                        session,
                        attempt_id=attempt_id,
                        question_id=state.row.id,
                        status="running",
                        child_attempt_id=state.row.execution_attempt_id,
                    )
                await session.commit()
                await progress.publish_committed()

        waves += 1
        executable = [_as_executable(state, attempt_id) for state in ready]
        outcomes = await _run_wave(worker, executable, concurrency=concurrency)

        async with factory() as session:
            with ProgressTracker() as progress:
                for question, outcome in zip(executable, outcomes, strict=True):
                    row = await session.get(ResearchQuestion, question.id)
                    if row is None:
                        raise ResearchQuestionExecutionError(
                            f"research question disappeared during execution: {question.id}"
                        )
                    if isinstance(outcome, BaseException):
                        reason = (str(outcome) or outcome.__class__.__name__)[:2000]
                        row.status = "failed"
                        row.outcome_reason = reason
                        await emit_question_status(
                            session,
                            attempt_id=attempt_id,
                            question_id=question.id,
                            status="failed",
                            child_attempt_id=row.execution_attempt_id,
                            reason=reason,
                        )
                        continue
                    row.status = "completed"
                    row.outcome_reason = None
                    if outcome.execution_attempt_id is not None:
                        row.execution_attempt_id = outcome.execution_attempt_id
                    await _persist_follow_ups(session, parent=question, outcome=outcome)
                    await emit_question_status(
                        session,
                        attempt_id=attempt_id,
                        question_id=question.id,
                        status="completed",
                        child_attempt_id=row.execution_attempt_id,
                    )
                await session.commit()
                await progress.publish_committed()


async def _load_graph(
    session: AsyncSession, attempt_id: str
) -> tuple[dict[str, _QuestionState], dict[str, set[str]]]:
    rows = (
        await session.execute(
            select(ResearchQuestion, KnowledgeQuestionRow.display_text)
            .join(
                KnowledgeQuestionRow,
                KnowledgeQuestionRow.id == ResearchQuestion.knowledge_question_id,
            )
            .where(ResearchQuestion.attempt_id == attempt_id)
            .order_by(ResearchQuestion.created_at, ResearchQuestion.id)
        )
    ).all()
    states = {question.id: _QuestionState(row=question, text=text) for question, text in rows}
    if not states:
        return states, {}
    expert_rows = (
        await session.execute(
            select(ResearchQuestionExpert).where(ResearchQuestionExpert.question_id.in_(states))
        )
    ).scalars()
    raised: dict[str, list[str]] = {question_id: [] for question_id in states}
    assigned: dict[str, str] = {}
    for link in expert_rows:
        if link.role == "raised_by":
            raised[link.question_id].append(link.expert_id)
        elif link.role == "assigned_to":
            assigned[link.question_id] = link.expert_id
    states = {
        question_id: _QuestionState(
            row=state.row,
            text=state.text,
            raised_by=tuple(raised[question_id]),
            assigned_to=assigned.get(question_id),
        )
        for question_id, state in states.items()
    }
    edges = (
        await session.execute(
            select(ResearchQuestionDependency).where(
                ResearchQuestionDependency.question_id.in_(states)
            )
        )
    ).scalars()
    dependencies = {question_id: set() for question_id in states}
    for edge in edges:
        dependencies[edge.question_id].add(edge.depends_on_question_id)
    return states, dependencies


def _ready_questions(
    states: dict[str, _QuestionState], dependencies: dict[str, set[str]]
) -> list[_QuestionState]:
    completed = {
        question_id for question_id, state in states.items() if state.row.status == "completed"
    }
    return [
        state
        for question_id, state in states.items()
        if state.row.status in {"pending", "blocked"}
        and state.assigned_to is not None
        and dependencies.get(question_id, set()) <= completed
    ]


def _as_executable(state: _QuestionState, attempt_id: str) -> ExecutableResearchQuestion:
    if state.assigned_to is None:
        raise ResearchQuestionExecutionError(
            f"research question has no assigned expert: {state.row.id}"
        )
    return ExecutableResearchQuestion(
        id=state.row.id,
        attempt_id=attempt_id,
        specific_question_id=state.row.specific_question_id,
        knowledge_question_id=state.row.knowledge_question_id,
        question=state.text,
        why_needed=state.row.why_needed,
        depth=state.row.depth,
        raised_by_expert_ids=state.raised_by,
        assigned_expert_id=state.assigned_to,
    )


async def _run_wave(
    worker: QuestionResearchWorker,
    questions: Sequence[ExecutableResearchQuestion],
    *,
    concurrency: int,
) -> list[QuestionResearchOutcome | BaseException]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(question: ExecutableResearchQuestion) -> QuestionResearchOutcome:
        async with semaphore:
            return await worker.research_question(question)

    return list(
        await asyncio.gather(*(run(question) for question in questions), return_exceptions=True)
    )


async def _persist_follow_ups(
    session: AsyncSession,
    *,
    parent: ExecutableResearchQuestion,
    outcome: QuestionResearchOutcome,
) -> None:
    for follow_up in outcome.follow_ups:
        assigned = follow_up.assigned_expert_id or parent.assigned_expert_id
        raised_by = follow_up.raised_by_expert_ids or (parent.assigned_expert_id,)
        child = await create_general_question(
            session,
            attempt_id=parent.attempt_id,
            specific_question_id=parent.specific_question_id,
            draft=GeneralQuestionDraft(
                question=follow_up.question,
                why_needed=follow_up.why_needed,
                raised_by_expert_ids=list(raised_by),
                assigned_expert_id=assigned,
                runtime_need_id=follow_up.runtime_need_id,
                origin="derived",
                depth=parent.depth + 1,
            ),
        )
        if child.id == parent.id:
            continue
        if follow_up.already_researched:
            child.status = "completed"
            child.execution_attempt_id = outcome.execution_attempt_id
        await add_question_dependency(
            session,
            question_id=child.id,
            depends_on_question_id=parent.id,
            reason="Evidence from the parent question exposed this follow-up.",
        )
        for dependency_id in follow_up.additional_dependency_ids:
            await add_question_dependency(
                session,
                question_id=child.id,
                depends_on_question_id=dependency_id,
                reason="Follow-up requires evidence from this question.",
            )


def _terminal_result(
    attempt_id: str,
    states: dict[str, _QuestionState],
    dependencies: dict[str, set[str]],
    waves: int,
) -> QuestionDagExecutionResult:
    if not states:
        return QuestionDagExecutionResult(attempt_id, "not_needed", 0, 0, 0, 0, waves)
    completed = sum(state.row.status == "completed" for state in states.values())
    failed = sum(state.row.status == "failed" for state in states.values())
    unassigned = sum(state.assigned_to is None for state in states.values())
    blocked = sum(state.row.status == "blocked" for state in states.values())
    unfinished = [state for state in states.values() if state.row.status != "completed"]
    if not unfinished:
        return QuestionDagExecutionResult(
            attempt_id, "completed", completed, failed, blocked, unassigned, waves
        )
    if unassigned:
        return QuestionDagExecutionResult(
            attempt_id,
            "waiting_for_assignment",
            completed,
            failed,
            blocked,
            unassigned,
            waves,
        )
    failed_ids = {
        question_id for question_id, state in states.items() if state.row.status == "failed"
    }
    blocked_by_failure = [
        question_id
        for question_id, required in dependencies.items()
        if required & failed_ids and states[question_id].row.status != "completed"
    ]
    if failed_ids or blocked_by_failure:
        return QuestionDagExecutionResult(
            attempt_id,
            "completed_with_gaps",
            completed,
            failed,
            blocked,
            unassigned,
            waves,
        )
    detail = ", ".join(state.row.id for state in unfinished)
    raise ResearchQuestionExecutionError(
        f"research question DAG cannot make progress; unresolved questions: {detail}"
    )
