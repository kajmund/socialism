"""LLM-backed FollowUpResearchPlanner using complete_structured. No retrieval."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_structured_retry
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.assessment import (
    AssessableEvidence,
    EvidenceReviewGroup,
    ResearchAssessmentDraft,
    group_evidence_for_review,
    review_excerpt,
)
from app.services.research.followup import (
    FollowUpNeedDraft,
    FollowUpPlannerError,
    RuntimeResearchNeed,
)
from app.services.research.models import RESEARCH_SOURCE_TYPES, ResearchPlan

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class FollowUpNeedModel(BaseModel):
    question: str
    why_needed: str
    source_types: list[str] = Field(default_factory=list)
    parent_research_need_id: str = ""
    source_gap: str = ""
    id: str = ""

    @field_validator(
        "question",
        "why_needed",
        "parent_research_need_id",
        "source_gap",
        "id",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("source_types", mode="before")
    @classmethod
    def list_of_text(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("must be a list")
        return [str(item).strip() for item in value if str(item).strip()]


class FollowUpPlanModel(BaseModel):
    needs: list[FollowUpNeedModel] = Field(default_factory=list)


def _plan_payload(plan: ResearchPlan) -> dict[str, object]:
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


def _assessment_payload(assessment: ResearchAssessmentDraft) -> dict[str, object]:
    return {
        "result": assessment.result,
        "rationale": assessment.rationale,
        "gaps": list(assessment.gaps),
        "contradictions": list(assessment.contradictions),
        "need_assessments": [
            {
                "research_need_id": row.research_need_id,
                "sufficient": row.sufficient,
                "missing_or_weak": row.missing_or_weak,
                "further_information": row.further_information,
                "contradictions": list(row.contradictions),
            }
            for row in assessment.need_assessments
        ],
    }


def _need_payload(row: RuntimeResearchNeed) -> dict[str, object]:
    return {
        "id": row.research_need_id,
        "question": row.question,
        "why_needed": row.why_needed,
        "origin": row.origin,
        "wave_number": row.wave_number,
        "parent_research_need_id": row.parent_research_need_id,
        "source_gap": row.source_gap,
        "source_types": list(row.source_types),
    }


def _evidence_payload(group: EvidenceReviewGroup) -> dict[str, object]:
    item = group.evidence
    return {
        "evidence_id": item.evidence_id,
        "research_need_id": item.research_need_id,
        "research_need_ids": list(group.research_need_ids),
        "duplicate_evidence_ids": list(group.duplicate_evidence_ids),
        "source_type": item.source_type,
        "status": item.status,
        "title": item.title,
        "excerpt": review_excerpt(item.excerpt),
        "locator": item.locator,
        "source_id": item.source_id,
        "source_url": item.source_url,
        "content_hash": item.content_hash,
    }


def _drafts_from_model(parsed: FollowUpPlanModel) -> list[FollowUpNeedDraft]:
    drafts: list[FollowUpNeedDraft] = []
    for row in parsed.needs:
        drafts.append(
            FollowUpNeedDraft(
                question=row.question,
                why_needed=row.why_needed,
                source_types=list(row.source_types),  # type: ignore[arg-type]
                parent_research_need_id=row.parent_research_need_id or None,
                source_gap=row.source_gap,
                proposed_id=row.id,
            )
        )
    return drafts


class LlmFollowUpPlanner:
    """Structured-output planner. Never retrieves or answers the question."""

    def __init__(
        self,
        *,
        completer: Completer | None = None,
        system_prompt: str,
        user_prompt: str,
    ) -> None:
        text = system_prompt.strip()
        user = user_prompt.strip()
        if not text:
            raise FollowUpPlannerError("research follow-up prompt is required")
        if not user:
            raise FollowUpPlannerError("research follow-up user prompt is required")
        self._completer = completer or complete_structured_retry
        self._system_prompt = text
        self._user_prompt = user

    async def plan_follow_ups(
        self,
        *,
        plan: ResearchPlan,
        assessment: ResearchAssessmentDraft,
        evidence: Sequence[AssessableEvidence],
        previous_needs: Sequence[RuntimeResearchNeed],
        available_source_types: Sequence[str] | None = None,
    ) -> Sequence[FollowUpNeedDraft]:
        source_types = (
            tuple(available_source_types)
            if available_source_types is not None
            else RESEARCH_SOURCE_TYPES
        )
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": render_prompt(
                    {"research.followup.user": self._user_prompt},
                    "research.followup.user",
                    source_types=", ".join(source_types),
                    plan_json=json.dumps(_plan_payload(plan), ensure_ascii=False),
                    assessment_json=json.dumps(
                        _assessment_payload(assessment), ensure_ascii=False
                    ),
                    previous_needs_json=json.dumps(
                        [_need_payload(row) for row in previous_needs],
                        ensure_ascii=False,
                    ),
                    evidence_json=json.dumps(
                        [
                            _evidence_payload(group)
                            for group in group_evidence_for_review(evidence)
                        ],
                        ensure_ascii=False,
                    ),
                ),
            },
        ]
        try:
            parsed = await self._completer(messages, FollowUpPlanModel)
        except Exception as exc:
            raise FollowUpPlannerError("Follow-up planner model call failed") from exc
        if not isinstance(parsed, FollowUpPlanModel):
            try:
                parsed = FollowUpPlanModel.model_validate(parsed)
            except Exception as exc:
                raise FollowUpPlannerError(
                    "Follow-up planner returned an invalid payload"
                ) from exc
        return _drafts_from_model(parsed)


async def build_llm_follow_up_planner(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
) -> LlmFollowUpPlanner:
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module=module,
        language="sv",
    )
    return LlmFollowUpPlanner(
        system_prompt=render_prompt(prompts, "research.followup.system"),
        user_prompt=prompts["research.followup.user"],
    )
