"""LLM-backed ResearchCompletenessReviewer. No live retrieval."""

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
    group_evidence_for_review,
    review_excerpt,
)
from app.services.research.completeness import (
    MaterialMissingQuestion,
    ResearchCompletenessDraft,
    ResearchCompletenessError,
    can_review_programmatically,
    programmatic_completeness,
    sanitize_completeness_draft,
)
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchPlan
from app.services.research.planner import ResearchObjective
from app.services.research.registry import production_registered_source_types

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class MissingQuestionModel(BaseModel):
    question: str
    why_needed: str = ""
    rationale: str = ""
    source_types: list[str] = Field(default_factory=list)

    @field_validator("question", "why_needed", "rationale", mode="before")
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


class CompletenessModel(BaseModel):
    result: Literal["complete", "incomplete"]
    rationale: str
    missing_questions: list[MissingQuestionModel] = Field(default_factory=list)

    @field_validator("rationale", mode="before")
    @classmethod
    def strip_rationale(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


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
        "provenance": dict(item.provenance),
        "retrieved_at": item.retrieved_at.isoformat(),
        "content_hash": item.content_hash,
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


def _need_payload(row: RuntimeResearchNeed) -> dict[str, object]:
    return {
        "research_need_id": row.research_need_id,
        "question": row.question,
        "why_needed": row.why_needed,
        "origin": row.origin,
        "wave_number": row.wave_number,
        "source_assessment_pass": row.source_assessment_pass,
        "source_completeness_pass": row.source_completeness_pass,
        "source_gap": row.source_gap,
        "question_key": row.question_key,
        "source_types": list(row.source_types),
    }


def _assessment_payload(draft: ResearchAssessmentDraft) -> dict[str, object]:
    return {
        "result": draft.result,
        "rationale": draft.rationale,
        "gaps": list(draft.gaps),
        "contradictions": list(draft.contradictions),
        "need_assessments": [
            {
                "research_need_id": row.research_need_id,
                "sufficient": row.sufficient,
                "missing_or_weak": row.missing_or_weak,
                "further_information": row.further_information,
            }
            for row in draft.need_assessments
        ],
    }


def _draft_from_model(
    parsed: CompletenessModel,
    *,
    provider: str | None,
    model: str | None,
    model_version: str | None,
) -> ResearchCompletenessDraft:
    return ResearchCompletenessDraft(
        result=parsed.result,
        rationale=parsed.rationale,
        missing_questions=[
            MaterialMissingQuestion(
                question=row.question,
                why_needed=row.why_needed,
                rationale=row.rationale,
                source_types=list(row.source_types),  # type: ignore[arg-type]
            )
            for row in parsed.missing_questions
        ],
        model_provider=provider,
        model_name=model,
        model_version=model_version,
    )


class LlmResearchCompletenessReviewer:
    """Structured-output completeness reviewer. Never retrieves."""

    def __init__(
        self,
        *,
        completer: Completer | None = None,
        system_prompt: str,
        user_prompt: str,
        provider: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
        source_types: Sequence[str] | None = None,
    ) -> None:
        text = system_prompt.strip()
        user = user_prompt.strip()
        if not text:
            raise ResearchCompletenessError("research completeness prompt is required")
        if not user:
            raise ResearchCompletenessError(
                "research completeness user prompt is required"
            )
        self._completer = completer or complete_structured_retry
        self._system_prompt = text
        self._user_prompt = user
        self._provider = provider
        self._model = model
        self._model_version = model_version
        offered = source_types if source_types is not None else production_registered_source_types()
        self._source_types = tuple(
            str(item).strip() for item in offered if str(item).strip()
        )

    async def review(
        self,
        *,
        objective: ResearchObjective | None,
        plan: ResearchPlan,
        runtime_needs: Sequence[RuntimeResearchNeed],
        assessment: ResearchAssessmentDraft | None,
        assessments: Sequence[ResearchAssessmentDraft],
        evidence: Sequence[AssessableEvidence],
        available_source_types: Sequence[str] | None = None,
    ) -> ResearchCompletenessDraft:
        if can_review_programmatically(objective):
            return programmatic_completeness(
                objective=objective,
                runtime_needs=runtime_needs,
                evidence=evidence,
            )
        history = list(assessments)
        if assessment is not None and (not history or history[-1] != assessment):
            history.append(assessment)
        types = (
            tuple(
                str(item).strip()
                for item in available_source_types
                if str(item).strip()
            )
            if available_source_types is not None
            else self._source_types
        )
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": render_prompt(
                    {"research.completeness.user": self._user_prompt},
                    "research.completeness.user",
                    source_types=", ".join(types),
                    objective=objective.objective if objective is not None else "",
                    objective_json=json.dumps(
                        {
                            "objective": objective.objective,
                            "context": dict(objective.context),
                        }
                        if objective is not None
                        else {},
                        ensure_ascii=False,
                    ),
                    plan_json=json.dumps(_plan_payload(plan), ensure_ascii=False),
                    runtime_needs_json=json.dumps(
                        [_need_payload(row) for row in runtime_needs],
                        ensure_ascii=False,
                    ),
                    assessment_json=json.dumps(
                        _assessment_payload(assessment)
                        if assessment is not None
                        else {},
                        ensure_ascii=False,
                    ),
                    assessments_json=json.dumps(
                        [_assessment_payload(row) for row in history],
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
            parsed = await self._completer(messages, CompletenessModel)
        except Exception as exc:
            raise ResearchCompletenessError(
                "Research completeness model call failed"
            ) from exc
        if not isinstance(parsed, CompletenessModel):
            try:
                parsed = CompletenessModel.model_validate(parsed)
            except Exception as exc:
                raise ResearchCompletenessError(
                    "Research completeness model returned an invalid payload"
                ) from exc
        return sanitize_completeness_draft(
            _draft_from_model(
                parsed,
                provider=self._provider,
                model=self._model,
                model_version=self._model_version,
            ),
            runtime_needs=runtime_needs,
            evidence=evidence,
            allowed_source_types=types,
        )


async def build_llm_research_completeness_reviewer(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
) -> LlmResearchCompletenessReviewer:
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module=module,
        language="sv",
    )
    return LlmResearchCompletenessReviewer(
        system_prompt=render_prompt(prompts, "research.completeness.system"),
        user_prompt=prompts["research.completeness.user"],
        provider=settings.llm_provider,
        model=settings.selected_llm_model,
        source_types=production_registered_source_types(),
    )
