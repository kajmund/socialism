"""LLM-backed ResearchAssessor using complete_structured. No live retrieval."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import complete_structured_retry
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.assessment import (
    AssessableEvidence,
    EvidenceReviewGroup,
    ResearchAssessmentDraft,
    ResearchAssessmentError,
    ResearchNeedAssessment,
    can_assess_programmatically,
    group_evidence_for_review,
    programmatic_assessment,
    review_excerpt,
    sanitize_assessment_draft,
)
from app.services.research.models import ResearchPlan

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class NeedSufficiencyModel(BaseModel):
    research_need_id: str
    sufficient: bool
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    missing_or_weak: str = ""
    contradictions: list[str] = Field(default_factory=list)
    further_information: str = ""

    @field_validator(
        "research_need_id",
        "missing_or_weak",
        "further_information",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("supporting_evidence_ids", "contradictions", mode="before")
    @classmethod
    def list_of_text(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("must be a list")
        return [str(item).strip() for item in value if str(item).strip()]


class EvidenceSufficiencyModel(BaseModel):
    result: Literal["sufficient", "insufficient"]
    rationale: str
    need_assessments: list[NeedSufficiencyModel] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    considered_evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("rationale", mode="before")
    @classmethod
    def strip_rationale(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("gaps", "contradictions", "considered_evidence_ids", mode="before")
    @classmethod
    def list_of_text(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("must be a list")
        return [str(item).strip() for item in value if str(item).strip()]


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
        "provider": item.provider,
        "score": item.score,
        "provenance": {k: v for k, v in item.provenance.items() if k != "legal_result"},
        "legal_result": (
            item.legal_result.model_dump(mode="json", exclude={"raw_text"})
            if item.legal_result else None
        ),
        "claims": list(item.claims),
        "retrieved_at": item.retrieved_at.isoformat(),
        "content_hash": item.content_hash,
        **(
            {
                "quality": {
                    "scoring_policy_version": item.quality.scoring_policy_version,
                    "authority": item.quality.authority,
                    "relevance": item.quality.relevance,
                    "currentness": item.quality.currentness,
                    "source_nature": item.quality.source_nature,
                    "independence_key": item.quality.independence_key,
                    "independent_source_count": item.quality.independent_source_count,
                    "flags": [flag.to_json() for flag in item.quality.flags],
                    "rationale": item.quality.rationale,
                    "model_provider": item.quality.model_provider,
                    "model_name": item.quality.model_name,
                    "model_version": item.quality.model_version,
                }
            }
            if item.quality is not None
            else {}
        ),
    }


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


def _draft_from_model(
    parsed: EvidenceSufficiencyModel,
    *,
    provider: str | None,
    model: str | None,
    model_version: str | None,
) -> ResearchAssessmentDraft:
    return ResearchAssessmentDraft(
        result=parsed.result,
        rationale=parsed.rationale,
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id=row.research_need_id,
                sufficient=row.sufficient,
                supporting_evidence_ids=list(row.supporting_evidence_ids),
                missing_or_weak=row.missing_or_weak,
                contradictions=list(row.contradictions),
                further_information=row.further_information or None,
            )
            for row in parsed.need_assessments
        ],
        gaps=list(parsed.gaps),
        contradictions=list(parsed.contradictions),
        considered_evidence_ids=list(parsed.considered_evidence_ids),
        model_provider=provider,
        model_name=model,
        model_version=model_version,
    )


class LlmResearchAssessor:
    """Structured-output assessor. Never retrieves; never invents source IDs."""

    def __init__(
        self,
        *,
        completer: Completer | None = None,
        system_prompt: str,
        user_prompt: str,
        provider: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
    ) -> None:
        text = system_prompt.strip()
        user = user_prompt.strip()
        if not text:
            raise ResearchAssessmentError("research assessment prompt is required")
        if not user:
            raise ResearchAssessmentError("research assessment user prompt is required")
        self._completer = completer or complete_structured_retry
        self._system_prompt = text
        self._user_prompt = user
        self._provider = provider
        self._model = model
        self._model_version = model_version

    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        if can_assess_programmatically(plan, evidence):
            return programmatic_assessment(
                plan,
                evidence,
                model_provider="programmatic",
                model_name=None,
                model_version=None,
            )
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": render_prompt(
                    {"research.assessment.user": self._user_prompt},
                    "research.assessment.user",
                    plan_json=json.dumps(_plan_payload(plan), ensure_ascii=False),
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
            parsed = await self._completer(messages, EvidenceSufficiencyModel)
        except Exception as exc:
            raise ResearchAssessmentError(
                "Evidence sufficiency model call failed"
            ) from exc
        if not isinstance(parsed, EvidenceSufficiencyModel):
            try:
                parsed = EvidenceSufficiencyModel.model_validate(parsed)
            except Exception as exc:
                raise ResearchAssessmentError(
                    "Evidence sufficiency model returned an invalid payload"
                ) from exc
        return sanitize_assessment_draft(
            _draft_from_model(
                parsed,
                provider=self._provider,
                model=self._model,
                model_version=self._model_version,
            ),
            plan=plan,
            evidence=evidence,
        )


async def build_llm_research_assessor(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
) -> LlmResearchAssessor:
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module=module,
        language="sv",
    )
    return LlmResearchAssessor(
        system_prompt=render_prompt(prompts, "research.assessment.system"),
        user_prompt=prompts["research.assessment.user"],
        provider=settings.llm_provider,
        model=settings.selected_llm_model,
    )
