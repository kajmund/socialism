"""Validate and snapshot ResearchPlan. Shared ResearchNeed taxonomy only."""

from __future__ import annotations

from typing import Any

from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    InvalidResearchPlanError,
    ResearchNeed,
    ResearchPlan,
    ResearchSourceType,
)

_SOURCE_TYPES: frozenset[str] = frozenset(RESEARCH_SOURCE_TYPES)


def validate_research_plan(plan: ResearchPlan) -> ResearchPlan:
    """Fail closed before an Attempt leaves created.

    Empty plan is valid. Duplicate IDs, empty questions, and unknown
    source_types are not.
    """
    seen_ids: set[str] = set()
    validated: list[ResearchNeed] = []
    for need in plan.needs:
        need_id = need.id.strip()
        if not need_id:
            raise InvalidResearchPlanError("ResearchNeed.id is required")
        if need_id in seen_ids:
            raise InvalidResearchPlanError(f"Duplicate ResearchNeed.id: {need_id}")
        seen_ids.add(need_id)
        question = need.question.strip()
        if not question:
            raise InvalidResearchPlanError(f"ResearchNeed {need_id} question is required")
        source_types = _require_source_types(need.source_types, need_id=need_id)
        validated.append(
            ResearchNeed(
                id=need_id,
                question=question,
                why_needed=need.why_needed,
                requested_by=list(need.requested_by),
                source_types=source_types,
            )
        )
    return ResearchPlan(needs=validated)


def research_plan_to_snapshot(plan: ResearchPlan) -> dict[str, Any]:
    return {
        "needs": [
            {
                "id": need.id,
                "question": need.question,
                "why_needed": need.why_needed,
                "requested_by": list(need.requested_by),
                "source_types": list(need.source_types),
            }
            for need in plan.needs
        ]
    }


def research_plan_from_snapshot(raw: object) -> ResearchPlan:
    if raw is None:
        return ResearchPlan()
    if not isinstance(raw, dict):
        raise InvalidResearchPlanError("research_plan_snapshot must be a JSON object")
    needs_raw = raw.get("needs", [])
    if not isinstance(needs_raw, list):
        raise InvalidResearchPlanError("research_plan_snapshot.needs must be a list")
    needs: list[ResearchNeed] = []
    for item in needs_raw:
        if not isinstance(item, dict):
            raise InvalidResearchPlanError("each ResearchNeed snapshot must be an object")
        source_types = item.get("source_types") or []
        if not isinstance(source_types, list):
            raise InvalidResearchPlanError("ResearchNeed.source_types must be a list")
        requested_by = item.get("requested_by") or []
        if not isinstance(requested_by, list):
            raise InvalidResearchPlanError("ResearchNeed.requested_by must be a list")
        needs.append(
            ResearchNeed(
                id=str(item.get("id") or ""),
                question=str(item.get("question") or ""),
                why_needed=str(item.get("why_needed") or ""),
                requested_by=[str(value) for value in requested_by],
                source_types=_require_source_types(
                    [str(value) for value in source_types],
                    need_id=str(item.get("id") or ""),
                ),
            )
        )
    return validate_research_plan(ResearchPlan(needs=needs))


def _require_source_types(
    values: list[str] | list[ResearchSourceType],
    *,
    need_id: str,
) -> list[ResearchSourceType]:
    out: list[ResearchSourceType] = []
    for raw in values:
        source_type = str(raw).strip()
        if source_type not in _SOURCE_TYPES:
            raise InvalidResearchPlanError(
                f"ResearchNeed {need_id} has unknown source_type={source_type!r}"
            )
        out.append(source_type)  # type: ignore[arg-type]
    return out
