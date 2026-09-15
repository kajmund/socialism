"""Follow-up ResearchNeed planning. Asks what to research; does not retrieve."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.services.execution.models import (
    INITIAL_RESEARCH_WAVE,
    RESEARCH_NEED_ORIGINS,
    RESEARCH_STOP_REASONS,
    ResearchNeedOrigin,
    ResearchStopReason,
)
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
)
from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    InvalidResearchPlanError,
    ResearchError,
    ResearchNeed,
    ResearchPlan,
    ResearchSourceType,
)
from app.services.research.plan import validate_research_plan

_SOURCE_TYPES: frozenset[str] = frozenset(RESEARCH_SOURCE_TYPES)


class FollowUpPlannerError(ResearchError):
    """Planner, model, or parsing failed. Not a no-novel-followups outcome."""


@dataclass(frozen=True)
class FollowUpNeedDraft:
    """Candidate follow-up. Orchestration assigns a stable id before persist."""

    question: str
    why_needed: str
    source_types: list[ResearchSourceType] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    modalities: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    parent_research_need_id: str | None = None
    source_gap: str = ""
    proposed_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_types", list(self.source_types))
        object.__setattr__(self, "domains", list(self.domains))
        object.__setattr__(self, "modalities", list(self.modalities))
        object.__setattr__(self, "capabilities", list(self.capabilities))


@dataclass(frozen=True)
class RuntimeResearchNeed:
    """Persisted runtime need: initial plan row or a derived follow-up."""

    research_need_id: str
    question: str
    why_needed: str
    requested_by: list[str] = field(default_factory=list)
    source_types: list[ResearchSourceType] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    modalities: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    origin: ResearchNeedOrigin = "initial"
    wave_number: int = INITIAL_RESEARCH_WAVE
    parent_research_need_id: str | None = None
    source_assessment_pass: int | None = None
    source_completeness_pass: int | None = None
    source_gap: str = ""
    question_key: str = ""

    def __post_init__(self) -> None:
        if self.origin not in RESEARCH_NEED_ORIGINS:
            raise FollowUpPlannerError(f"Unknown research need origin: {self.origin}")
        object.__setattr__(self, "requested_by", list(self.requested_by))
        object.__setattr__(self, "source_types", list(self.source_types))
        object.__setattr__(self, "domains", list(self.domains))
        object.__setattr__(self, "modalities", list(self.modalities))
        object.__setattr__(self, "capabilities", list(self.capabilities))
        key = self.question_key or research_question_key(self.question)
        object.__setattr__(self, "question_key", key)

    def as_need(self) -> ResearchNeed:
        return ResearchNeed(
            id=self.research_need_id,
            question=self.question,
            why_needed=self.why_needed,
            requested_by=list(self.requested_by),
            source_types=list(self.source_types),
            domains=list(self.domains),
            modalities=list(self.modalities),
            capabilities=list(self.capabilities),
        )


class FollowUpResearchPlanner(Protocol):
    async def plan_follow_ups(
        self,
        *,
        plan: ResearchPlan,
        assessment: ResearchAssessmentDraft,
        evidence: Sequence[AssessableEvidence],
        previous_needs: Sequence[RuntimeResearchNeed],
    ) -> Sequence[FollowUpNeedDraft]: ...


class NoOpFollowUpPlanner:
    """Deterministic empty planner. Used when no follow-up adapter is injected."""

    async def plan_follow_ups(
        self,
        *,
        plan: ResearchPlan,
        assessment: ResearchAssessmentDraft,
        evidence: Sequence[AssessableEvidence],
        previous_needs: Sequence[RuntimeResearchNeed],
    ) -> Sequence[FollowUpNeedDraft]:
        return []


def normalize_research_question(question: str) -> str:
    return " ".join(question.casefold().split())


def research_question_key(question: str) -> str:
    """Deterministic hash of a normalized question. No embeddings."""
    return hashlib.sha256(normalize_research_question(question).encode("utf-8")).hexdigest()


def runtime_needs_from_plan(
    plan: ResearchPlan, *, wave_number: int = INITIAL_RESEARCH_WAVE
) -> list[RuntimeResearchNeed]:
    return [
        RuntimeResearchNeed(
            research_need_id=need.id,
            question=need.question,
            why_needed=need.why_needed,
            requested_by=list(need.requested_by),
            source_types=list(need.source_types),
            domains=list(need.domains),
            modalities=list(need.modalities),
            capabilities=list(need.capabilities),
            origin="initial",
            wave_number=wave_number,
        )
        for need in plan.needs
    ]


def plan_from_runtime_needs(needs: Sequence[RuntimeResearchNeed]) -> ResearchPlan:
    return ResearchPlan(needs=[row.as_need() for row in needs])


def assign_follow_up_need_id(
    *,
    wave_number: int,
    index: int,
    existing_ids: set[str],
    proposed_id: str = "",
    id_prefix: str = "followup",
) -> str:
    candidate = proposed_id.strip()
    if candidate and candidate not in existing_ids:
        return candidate
    prefix = id_prefix.strip() or "followup"
    base = f"{prefix}_{wave_number}_{index}"
    if base not in existing_ids:
        return base
    suffix = 1
    while f"{base}_{suffix}" in existing_ids:
        suffix += 1
    return f"{base}_{suffix}"


def _known_parent(
    parent_id: str | None, previous_needs: Sequence[RuntimeResearchNeed]
) -> str | None:
    if parent_id is None:
        return None
    text = parent_id.strip()
    if not text:
        return None
    known = {row.research_need_id for row in previous_needs}
    if text in known:
        return text
    return None


def validate_follow_up_drafts(
    drafts: Sequence[FollowUpNeedDraft],
    *,
    previous_needs: Sequence[RuntimeResearchNeed],
    wave_number: int,
    assessment_pass: int | None = None,
    origin: ResearchNeedOrigin = "derived",
    source_completeness_pass: int | None = None,
    id_prefix: str = "followup",
) -> list[RuntimeResearchNeed]:
    """Keep valid novel candidates. Invalid drafts are dropped, not executed."""
    existing_ids = {row.research_need_id for row in previous_needs}
    seen_keys = {row.question_key for row in previous_needs}
    accepted: list[RuntimeResearchNeed] = []
    for index, draft in enumerate(drafts, start=1):
        question = draft.question.strip()
        why_needed = draft.why_needed.strip()
        source_gap = draft.source_gap.strip() or why_needed
        if not question or not why_needed:
            continue
        key = research_question_key(question)
        if key in seen_keys:
            continue
        source_types = [
            str(item).strip()
            for item in draft.source_types
            if str(item).strip()
        ]
        if not source_types or any(item not in _SOURCE_TYPES for item in source_types):
            continue
        need_id = assign_follow_up_need_id(
            wave_number=wave_number,
            index=index,
            existing_ids=existing_ids,
            proposed_id=draft.proposed_id,
            id_prefix=id_prefix,
        )
        try:
            validated = validate_research_plan(
                ResearchPlan(
                    needs=[
                        ResearchNeed(
                            id=need_id,
                            question=question,
                            why_needed=why_needed,
                            source_types=source_types,  # type: ignore[arg-type]
                            domains=list(draft.domains),
                            modalities=list(draft.modalities),
                            capabilities=list(draft.capabilities),
                        )
                    ]
                )
            )
        except InvalidResearchPlanError:
            continue
        need = validated.needs[0]
        existing_ids.add(need.id)
        seen_keys.add(key)
        accepted.append(
            RuntimeResearchNeed(
                research_need_id=need.id,
                question=need.question,
                why_needed=need.why_needed,
                requested_by=list(need.requested_by),
                source_types=list(need.source_types),
                domains=list(need.domains),
                modalities=list(need.modalities),
                capabilities=list(need.capabilities),
                origin=origin,
                wave_number=wave_number,
                parent_research_need_id=_known_parent(
                    draft.parent_research_need_id, previous_needs
                ),
                source_assessment_pass=assessment_pass,
                source_completeness_pass=source_completeness_pass,
                source_gap=source_gap,
                question_key=key,
            )
        )
    return accepted


def take_needs_within_budget(
    candidates: Sequence[RuntimeResearchNeed],
    *,
    current_count: int,
    max_needs: int,
) -> list[RuntimeResearchNeed]:
    remaining = max_needs - current_count
    if remaining <= 0:
        return []
    return list(candidates[:remaining])


def require_stop_reason(value: str) -> ResearchStopReason:
    if value not in RESEARCH_STOP_REASONS:
        raise FollowUpPlannerError(f"Unknown research stop reason: {value}")
    return value  # type: ignore[return-value]


def next_assessment_pass(wave_number: int) -> int:
    return wave_number + 1
