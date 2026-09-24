"""Initial ResearchPlan decomposition. Asks what to research; does not retrieve."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.services.research.knowledge_question import research_question_key
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


class ResearchPlannerError(ResearchError):
    """Planner, model, or parsing failed before research may start."""


class InvalidResearchObjectiveError(ResearchError, ValueError):
    """Objective is missing, empty, or trivial. Research must not start."""


@dataclass(frozen=True)
class ResearchObjective:
    """Persisted research question. Tenant/case scope stays on the Run."""

    objective: str
    context: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective", require_research_objective(self.objective))
        raw = self.context
        if not isinstance(raw, dict):
            raise InvalidResearchObjectiveError(
                "research_objective context must be a JSON object"
            )
        object.__setattr__(self, "context", dict(raw))


@dataclass(frozen=True)
class ResearchNeedDraft:
    """Candidate initial need. Orchestration assigns the authoritative id."""

    question: str
    why_needed: str
    source_types: list[ResearchSourceType] = field(default_factory=list)
    proposed_id: str = ""
    generated_from: str = ""
    original_need_id: str = ""
    original_question: str = ""
    normalization_reason: str = ""
    already_normalized: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_types", list(self.source_types))


class ResearchPlanner(Protocol):
    async def plan_research(
        self,
        *,
        objective: ResearchObjective,
        available_source_types: Sequence[str] | None = None,
    ) -> Sequence[ResearchNeedDraft]: ...


class FakeResearchPlanner:
    """Deterministic planner for tests. Never calls a model."""

    def __init__(self, drafts: Sequence[ResearchNeedDraft] | None = None) -> None:
        self.drafts = list(drafts or [])
        self.calls: list[ResearchObjective] = []
        self.available_source_types_calls: list[tuple[str, ...]] = []

    async def plan_research(
        self,
        *,
        objective: ResearchObjective,
        available_source_types: Sequence[str] | None = None,
    ) -> Sequence[ResearchNeedDraft]:
        self.calls.append(objective)
        self.available_source_types_calls.append(tuple(available_source_types or ()))
        return list(self.drafts)


def require_research_objective(value: str) -> str:
    """Empty or punctuation-only text is not a research objective."""
    cleaned = " ".join(str(value).split())
    if not cleaned or not any(character.isalnum() for character in cleaned):
        raise InvalidResearchObjectiveError(
            "research_objective must contain a concrete question or task"
        )
    return cleaned


def research_objective_to_snapshot(objective: ResearchObjective) -> dict[str, object]:
    return {"objective": objective.objective, "context": dict(objective.context)}


def research_objective_from_snapshot(raw: object) -> ResearchObjective:
    if raw is None:
        raise InvalidResearchObjectiveError("research_objective_snapshot is required")
    if not isinstance(raw, dict):
        raise InvalidResearchObjectiveError(
            "research_objective_snapshot must be a JSON object"
        )
    context = raw.get("context") or {}
    if not isinstance(context, dict):
        raise InvalidResearchObjectiveError(
            "research_objective_snapshot.context must be a JSON object"
        )
    return ResearchObjective(
        objective=str(raw.get("objective") or ""),
        context=dict(context),
    )


def assign_initial_need_id(
    *,
    index: int,
    existing_ids: set[str],
    proposed_id: str = "",
) -> str:
    candidate = proposed_id.strip()
    if candidate and candidate not in existing_ids:
        return candidate
    base = f"research_{index}"
    if base not in existing_ids:
        return base
    suffix = 1
    while f"{base}_{suffix}" in existing_ids:
        suffix += 1
    return f"{base}_{suffix}"


def plan_from_planner_drafts(
    drafts: Sequence[ResearchNeedDraft],
    *,
    allowed_source_types: Sequence[str] | None = None,
) -> ResearchPlan:
    """Turn planner candidates into a ResearchPlan. Validation stays authoritative.

    A generated plan must contain at least one need. ``allowed_source_types``
    is the executable registry for this attempt; catalog membership alone
    is not enough when that set is provided.
    """
    if not drafts:
        raise InvalidResearchPlanError(
            "generated ResearchPlan must contain at least one need"
        )
    allowed = (
        frozenset(str(item).strip() for item in allowed_source_types if str(item).strip())
        if allowed_source_types is not None
        else _SOURCE_TYPES
    )
    existing_ids: set[str] = set()
    seen_keys: set[str] = set()
    needs: list[ResearchNeed] = []
    for index, draft in enumerate(drafts, start=1):
        question = draft.question.strip()
        why_needed = draft.why_needed.strip()
        if not question:
            raise InvalidResearchPlanError(
                f"ResearchNeed {index} question is required"
            )
        if not why_needed:
            raise InvalidResearchPlanError(
                f"ResearchNeed {index} why_needed is required"
            )
        key = research_question_key(question)
        if key in seen_keys:
            raise InvalidResearchPlanError(
                f"Duplicate research question: {question}"
            )
        source_types = [
            str(item).strip()
            for item in draft.source_types
            if str(item).strip()
        ]
        if not source_types:
            raise InvalidResearchPlanError(
                f"ResearchNeed {index} source_types is required"
            )
        if any(item not in allowed for item in source_types):
            unknown = next(item for item in source_types if item not in allowed)
            kind = "unknown" if allowed_source_types is None else "unavailable"
            raise InvalidResearchPlanError(
                f"ResearchNeed {index} has {kind} source_type={unknown!r}"
            )
        need_id = assign_initial_need_id(
            index=index,
            existing_ids=existing_ids,
            proposed_id=draft.proposed_id,
        )
        existing_ids.add(need_id)
        seen_keys.add(key)
        needs.append(
            ResearchNeed(
                id=need_id,
                question=question,
                why_needed=why_needed,
                source_types=source_types,  # type: ignore[arg-type]
                generated_from=draft.generated_from,
                original_need_id=draft.original_need_id,
                original_question=draft.original_question,
                normalization_reason=draft.normalization_reason,
                already_normalized=draft.already_normalized,
            )
        )
    return validate_research_plan(ResearchPlan(needs=needs))
