"""Match general research questions to experts, creating one when needed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    ExecutionAttempt,
    ExecutionRun,
    KnowledgeQuestionRow,
    Persona,
    ResearchQuestion,
    ResearchQuestionExpert,
)
from app.services.research.question_domain import assign_question_expert


class ResearchQuestionExpertAssignmentError(RuntimeError):
    """Expert matching or creation returned an invalid result."""


@dataclass(frozen=True)
class ExpertCandidateIdentity:
    expert_id: str
    name: str
    profile: str


@dataclass(frozen=True)
class ExpertAssignmentQuestion:
    question_id: str
    question: str
    why_needed: str
    customer_id: int
    module: str


class ResearchQuestionExpertMatcher(Protocol):
    async def match_expert(
        self,
        *,
        question: ExpertAssignmentQuestion,
        candidates: tuple[ExpertCandidateIdentity, ...],
    ) -> str | None: ...


class ResearchQuestionExpertCreator(Protocol):
    async def create_expert(
        self,
        session: AsyncSession,
        *,
        question: ExpertAssignmentQuestion,
    ) -> ExpertCandidateIdentity: ...


@dataclass(frozen=True)
class ExpertAssignmentResult:
    question_count: int
    matched_count: int
    created_count: int


async def assign_unowned_research_questions(
    session: AsyncSession,
    *,
    attempt_id: str,
    matcher: ResearchQuestionExpertMatcher,
    creator: ResearchQuestionExpertCreator,
) -> ExpertAssignmentResult:
    rows = (
        await session.execute(
            select(
                ResearchQuestion,
                KnowledgeQuestionRow.display_text,
                ExecutionRun.customer_id,
                ExecutionRun.module,
            )
            .join(
                KnowledgeQuestionRow,
                KnowledgeQuestionRow.id == ResearchQuestion.knowledge_question_id,
            )
            .join(ExecutionAttempt, ExecutionAttempt.id == ResearchQuestion.attempt_id)
            .join(ExecutionRun, ExecutionRun.id == ExecutionAttempt.run_id)
            .where(
                ResearchQuestion.attempt_id == attempt_id,
                ResearchQuestion.status == "unassigned",
            )
            .order_by(ResearchQuestion.created_at, ResearchQuestion.id)
        )
    ).all()
    matched_count = 0
    created_count = 0
    candidate_cache: dict[tuple[int, str], list[ExpertCandidateIdentity]] = {}
    for row, text, customer_id, module in rows:
        raised_by = list(
            (
                await session.execute(
                    select(ResearchQuestionExpert.expert_id).where(
                        ResearchQuestionExpert.question_id == row.id,
                        ResearchQuestionExpert.role == "raised_by",
                    )
                )
            ).scalars()
        )
        if not raised_by:
            raise ResearchQuestionExpertAssignmentError(
                f"research question has no raised_by expert: {row.id}"
            )
        cache_key = (customer_id, module)
        if cache_key not in candidate_cache:
            candidate_cache[cache_key] = await _expert_candidates(session, customer_id=customer_id)
        question = ExpertAssignmentQuestion(
            question_id=row.id,
            question=text,
            why_needed=row.why_needed,
            customer_id=customer_id,
            module=module,
        )
        candidates = tuple(candidate_cache[cache_key])
        expert_id = await matcher.match_expert(
            question=question,
            candidates=candidates,
        )
        if expert_id is not None:
            if expert_id not in {candidate.expert_id for candidate in candidates}:
                raise ResearchQuestionExpertAssignmentError(
                    f"matcher returned an expert outside the customer catalog: {expert_id}"
                )
            matched_count += 1
        else:
            created = await creator.create_expert(session, question=question)
            persona = await session.get(Persona, created.expert_id)
            if persona is None or persona.customer_id != customer_id or persona.kind != "expert":
                raise ResearchQuestionExpertAssignmentError(
                    "creator did not persist a customer-scoped expert Persona"
                )
            expert_id = created.expert_id
            candidate_cache[cache_key].append(created)
            created_count += 1
        await assign_question_expert(
            session,
            question_id=row.id,
            expert_id=expert_id,
        )
    await session.flush()
    return ExpertAssignmentResult(
        question_count=len(rows),
        matched_count=matched_count,
        created_count=created_count,
    )


async def _expert_candidates(
    session: AsyncSession, *, customer_id: int
) -> list[ExpertCandidateIdentity]:
    personas = list(
        (
            await session.execute(
                select(Persona)
                .where(
                    Persona.customer_id == customer_id,
                    Persona.kind == "expert",
                )
                .order_by(Persona.updated_at, Persona.id)
            )
        ).scalars()
    )
    return [_identity_from_persona(persona) for persona in personas]


def _identity_from_persona(persona: Persona) -> ExpertCandidateIdentity:
    return ExpertCandidateIdentity(
        expert_id=persona.id,
        name=persona.name,
        profile=_persona_profile_text(persona),
    )


def _persona_profile_text(persona: Persona) -> str:
    raw = persona.profile if isinstance(persona.profile, dict) else {}
    values = [persona.quote]
    for key, label in (
        ("kompetensomrade", "Kompetensområde"),
        ("radgivningsstil", "Rådgivningsstil"),
        ("yrkesbakgrund", "Yrkesbakgrund"),
        ("professionell_anekdot", "Anekdot"),
    ):
        value = str(raw.get(key) or "").strip()
        if value and value != "—":
            values.append(f"{label}: {value}")
    return "\n".join(value for value in values if value and value != "—")
