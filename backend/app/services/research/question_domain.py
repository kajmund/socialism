"""Specific questions and expert-owned general questions for research execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    ResearchQuestion,
    ResearchQuestionDependency,
    ResearchQuestionExpert,
    SpecificQuestion,
)
from app.services.execution.service import get_attempt, get_run, new_id
from app.services.research.composition import build_standard_question_graph
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.knowledge_question import identity_from_text, tenant_question_scope

SpecificQuestionOrigin = Literal["expertgranskning", "expert_chat", "api"]
QuestionExpertRole = Literal["raised_by", "assigned_to"]


class ResearchQuestionDomainError(ValueError):
    """Question graph violates scope, ownership, or acyclic dependency rules."""


@dataclass(frozen=True)
class GeneralQuestionDraft:
    question: str
    why_needed: str = ""
    raised_by_expert_ids: list[str] = field(default_factory=list)
    assigned_expert_id: str | None = None
    runtime_need_id: str | None = None
    origin: str = "initial"
    depth: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "raised_by_expert_ids", list(self.raised_by_expert_ids))
        if not self.question.strip():
            raise ResearchQuestionDomainError("general question is required")
        if self.depth < 0:
            raise ResearchQuestionDomainError("question depth must be >= 0")


async def create_specific_question(
    session: AsyncSession,
    *,
    run_id: str,
    text: str,
    context: dict[str, object],
    origin_kind: SpecificQuestionOrigin,
    origin_ref: str | None = None,
) -> SpecificQuestion:
    await get_run(session, run_id)
    question = text.strip()
    if not question:
        raise ResearchQuestionDomainError("specific question is required")
    row = SpecificQuestion(
        id=new_id(),
        run_id=run_id,
        text=question,
        context=dict(context),
        origin_kind=origin_kind,
        origin_ref=origin_ref,
        status="open",
    )
    session.add(row)
    await session.flush()
    return row


async def create_general_question(
    session: AsyncSession,
    *,
    attempt_id: str,
    specific_question_id: str,
    draft: GeneralQuestionDraft,
) -> ResearchQuestion:
    attempt = await get_attempt(session, attempt_id)
    run = await get_run(session, attempt.run_id)
    specific = await session.get(SpecificQuestion, specific_question_id)
    if specific is None:
        raise ResearchQuestionDomainError(f"specific question not found: {specific_question_id}")
    if specific.run_id != run.id:
        raise ResearchQuestionDomainError(
            "specific question and Attempt must belong to the same Run"
        )

    graph = build_standard_question_graph()
    canonical = await graph.upsert_question(
        session,
        identity_from_text(draft.question),
        tenant_question_scope(run.customer_id),
    )
    result = await session.execute(
        select(ResearchQuestion).where(
            ResearchQuestion.attempt_id == attempt_id,
            ResearchQuestion.specific_question_id == specific_question_id,
            ResearchQuestion.knowledge_question_id == canonical.id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ResearchQuestion(
            id=new_id(),
            attempt_id=attempt_id,
            specific_question_id=specific_question_id,
            knowledge_question_id=canonical.id,
            runtime_need_id=draft.runtime_need_id,
            why_needed=draft.why_needed.strip(),
            status="pending" if draft.assigned_expert_id else "unassigned",
            origin=draft.origin,
            depth=draft.depth,
        )
        session.add(row)
        await session.flush()
    for expert_id in draft.raised_by_expert_ids:
        await add_question_expert(
            session, question_id=row.id, expert_id=expert_id, role="raised_by"
        )
    if draft.assigned_expert_id:
        await assign_question_expert(
            session, question_id=row.id, expert_id=draft.assigned_expert_id
        )
    await session.flush()
    return row


async def add_question_expert(
    session: AsyncSession,
    *,
    question_id: str,
    expert_id: str,
    role: QuestionExpertRole,
) -> ResearchQuestionExpert:
    await _require_question(session, question_id)
    normalized = expert_id.strip()
    if not normalized:
        raise ResearchQuestionDomainError("expert_id is required")
    result = await session.execute(
        select(ResearchQuestionExpert).where(
            ResearchQuestionExpert.question_id == question_id,
            ResearchQuestionExpert.expert_id == normalized,
            ResearchQuestionExpert.role == role,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    row = ResearchQuestionExpert(
        id=new_id(), question_id=question_id, expert_id=normalized, role=role
    )
    session.add(row)
    await session.flush()
    return row


async def assign_question_expert(
    session: AsyncSession,
    *,
    question_id: str,
    expert_id: str,
) -> ResearchQuestionExpert:
    question = await _require_question(session, question_id)
    await session.execute(
        delete(ResearchQuestionExpert).where(
            ResearchQuestionExpert.question_id == question_id,
            ResearchQuestionExpert.role == "assigned_to",
        )
    )
    assigned = await add_question_expert(
        session, question_id=question_id, expert_id=expert_id, role="assigned_to"
    )
    if question.status == "unassigned":
        question.status = "pending"
    return assigned


async def add_question_dependency(
    session: AsyncSession,
    *,
    question_id: str,
    depends_on_question_id: str,
    reason: str = "",
) -> ResearchQuestionDependency:
    if question_id == depends_on_question_id:
        raise ResearchQuestionDomainError("a question cannot depend on itself")
    question = await _require_question(session, question_id)
    dependency = await _require_question(session, depends_on_question_id)
    if question.attempt_id != dependency.attempt_id:
        raise ResearchQuestionDomainError("question dependencies must stay inside one Attempt")
    if await _would_create_cycle(
        session,
        attempt_id=question.attempt_id,
        question_id=question_id,
        depends_on_question_id=depends_on_question_id,
    ):
        raise ResearchQuestionDomainError("question dependency would create a cycle")
    result = await session.execute(
        select(ResearchQuestionDependency).where(
            ResearchQuestionDependency.question_id == question_id,
            ResearchQuestionDependency.depends_on_question_id == depends_on_question_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    row = ResearchQuestionDependency(
        id=new_id(),
        question_id=question_id,
        depends_on_question_id=depends_on_question_id,
        reason=reason.strip(),
    )
    session.add(row)
    if question.status == "pending":
        question.status = "blocked"
    await session.flush()
    return row


async def materialize_runtime_needs_as_questions(
    session: AsyncSession,
    *,
    attempt_id: str,
    specific_question_id: str,
    needs: Sequence[RuntimeResearchNeed],
    expert_by_requester: Mapping[str, str],
) -> list[ResearchQuestion]:
    """Compatibility bridge. New callers should create general questions directly."""
    rows: list[ResearchQuestion] = []
    for need in needs:
        raised = list(
            dict.fromkeys(
                expert_by_requester[requester]
                for requester in need.requested_by
                if requester in expert_by_requester
            )
        )
        rows.append(
            await create_general_question(
                session,
                attempt_id=attempt_id,
                specific_question_id=specific_question_id,
                draft=GeneralQuestionDraft(
                    question=need.question,
                    why_needed=need.why_needed,
                    raised_by_expert_ids=raised,
                    assigned_expert_id=raised[0] if raised else None,
                    runtime_need_id=need.research_need_id,
                    origin=need.origin,
                    depth=need.wave_number,
                ),
            )
        )
    return rows


async def _require_question(session: AsyncSession, question_id: str) -> ResearchQuestion:
    row = await session.get(ResearchQuestion, question_id)
    if row is None:
        raise ResearchQuestionDomainError(f"research question not found: {question_id}")
    return row


async def _would_create_cycle(
    session: AsyncSession,
    *,
    attempt_id: str,
    question_id: str,
    depends_on_question_id: str,
) -> bool:
    question_ids = set(
        (
            await session.execute(
                select(ResearchQuestion.id).where(ResearchQuestion.attempt_id == attempt_id)
            )
        ).scalars()
    )
    edges = (
        await session.execute(
            select(
                ResearchQuestionDependency.question_id,
                ResearchQuestionDependency.depends_on_question_id,
            ).where(ResearchQuestionDependency.question_id.in_(question_ids))
        )
    ).all()
    adjacency: dict[str, set[str]] = {item: set() for item in question_ids}
    for source, target in edges:
        adjacency.setdefault(source, set()).add(target)
    adjacency.setdefault(question_id, set()).add(depends_on_question_id)
    stack = [depends_on_question_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == question_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(adjacency.get(current, ()))
    return False
