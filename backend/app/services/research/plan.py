"""Validate and snapshot ResearchPlan. Shared ResearchNeed taxonomy only."""

from __future__ import annotations

from dataclasses import replace
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
    source_types are not. Domain/modality/capability tokens are preserved.
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
            replace(
                need,
                id=need_id,
                question=question,
                why_needed=need.why_needed,
                requested_by=list(need.requested_by),
                source_types=source_types,
                domains=_require_constraint_tokens(
                    getattr(need, "domains", ()), field="domains", need_id=need_id
                ),
                modalities=_require_constraint_tokens(
                    getattr(need, "modalities", ()), field="modalities", need_id=need_id
                ),
                capabilities=_require_constraint_tokens(
                    getattr(need, "capabilities", ()),
                    field="capabilities",
                    need_id=need_id,
                ),
                generated_from=str(getattr(need, "generated_from", "") or ""),
                original_need_id=str(getattr(need, "original_need_id", "") or ""),
                original_question=str(getattr(need, "original_question", "") or ""),
                normalization_reason=str(getattr(need, "normalization_reason", "") or ""),
                already_normalized=bool(getattr(need, "already_normalized", False)),
                knowledge_question_id=str(getattr(need, "knowledge_question_id", "") or ""),
            )
        )
    return ResearchPlan(needs=validated)


def research_plan_to_snapshot(plan: ResearchPlan) -> dict[str, Any]:
    return {
        "needs": [_need_snapshot(need) for need in plan.needs]
    }


def _need_snapshot(need: ResearchNeed) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": need.id,
        "question": need.question,
        "why_needed": need.why_needed,
        "requested_by": list(need.requested_by),
        "source_types": list(need.source_types),
        "domains": list(need.domains),
        "modalities": list(need.modalities),
        "capabilities": list(need.capabilities),
    }
    if need.generated_from:
        payload["generated_from"] = need.generated_from
    if need.original_need_id:
        payload["original_need_id"] = need.original_need_id
    if need.original_question:
        payload["original_question"] = need.original_question
    if need.normalization_reason:
        payload["normalization_reason"] = need.normalization_reason
    if need.already_normalized:
        payload["already_normalized"] = True
    if need.knowledge_question_id:
        payload["knowledge_question_id"] = need.knowledge_question_id
    return payload


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
        need_id = str(item.get("id") or "")
        needs.append(
            ResearchNeed(
                id=need_id,
                question=str(item.get("question") or ""),
                why_needed=str(item.get("why_needed") or ""),
                requested_by=[str(value) for value in requested_by],
                source_types=_require_source_types(
                    [str(value) for value in source_types],
                    need_id=need_id,
                ),
                domains=_require_constraint_tokens(
                    item.get("domains") or [], field="domains", need_id=need_id
                ),
                modalities=_require_constraint_tokens(
                    item.get("modalities") or [], field="modalities", need_id=need_id
                ),
                capabilities=_require_constraint_tokens(
                    item.get("capabilities") or [],
                    field="capabilities",
                    need_id=need_id,
                ),
                generated_from=str(item.get("generated_from") or ""),
                original_need_id=str(item.get("original_need_id") or ""),
                original_question=str(item.get("original_question") or ""),
                normalization_reason=str(item.get("normalization_reason") or ""),
                already_normalized=bool(item.get("already_normalized") or False),
                knowledge_question_id=str(item.get("knowledge_question_id") or ""),
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


def _require_constraint_tokens(values: object, *, field: str, need_id: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise InvalidResearchPlanError(f"ResearchNeed {need_id} {field} must be a list")
    return [str(item).strip() for item in values if str(item).strip()]
