"""Composable Jev gates around existing assessor and completeness reviewers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence

from app.observability.research import (
    emit_jev_shadow_comparison,
    emit_jev_short_circuit,
    record_assessor_llm,
    record_completeness_llm,
    record_follow_up_wave_avoided,
)
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
    ResearchAssessor,
    ResearchNeedAssessment,
    can_assess_programmatically,
    sanitize_assessment_draft,
)
from app.services.research.completeness import (
    ResearchCompletenessDraft,
    ResearchCompletenessReviewer,
    can_review_programmatically,
)
from app.services.research.evidence_screen import (
    EvidenceJevScores,
    order_evidence_for_state,
    screen_evidence,
    screening_objective,
)
from app.services.research.fast_controller import (
    ResearchFastController,
    ResearchFastDecision,
    research_jev_available,
    research_jev_mode,
)
from app.services.research.fast_state import found_evidence_ids
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchPlan
from app.services.research.planner import ResearchObjective

SUFFICIENT_RATIONALE = (
    "Jev high-confidence sufficient. Supporting IDs are persisted found evidence."
)
COMPLETE_RATIONALE = "Jev high-confidence complete."


class GatedResearchAssessor:
    """Programmatic → Jev → optional LLM assessor. Jev never fails research."""

    def __init__(
        self,
        inner: ResearchAssessor,
        controller: ResearchFastController | None = None,
    ) -> None:
        self._inner = inner
        self._controller = controller or ResearchFastController()
        self._evidence_scores: dict[tuple[str, str], EvidenceJevScores] = {}

    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        if not research_jev_available() or can_assess_programmatically(plan, evidence):
            return await self._inner.assess(plan, evidence)
        if research_jev_mode() == "shadow":
            decision, draft, latency_ms = await _parallel_shadow(
                self._assess_jev(plan, evidence), lambda: self._call_inner(plan, evidence)
            )
            _compare_assessment(decision, draft, llm_latency_ms=latency_ms)
            return draft
        decision = await self._assess_jev(plan, evidence)
        if decision.mode == "active" and decision.would_short_circuit:
            draft = _sufficient_draft(plan, evidence, decision)
            if draft is not None:
                record_assessor_llm(skipped=True)
                emit_jev_short_circuit(
                    gate="assessment",
                    mode=decision.mode,
                    decision=decision.outcome,
                    latency_ms=decision.latency_ms,
                )
                return sanitize_assessment_draft(draft, plan=plan, evidence=evidence)
        started = time.perf_counter()
        draft = await self._call_inner(plan, evidence)
        llm_latency_ms = (time.perf_counter() - started) * 1000
        _compare_assessment(decision, draft, llm_latency_ms=llm_latency_ms)
        return draft

    async def _assess_jev(
        self, plan: ResearchPlan, evidence: Sequence[AssessableEvidence],
    ) -> ResearchFastDecision:
        scores = await screen_evidence(
            objective=screening_objective(objective=None, plan=plan),
            evidence=evidence,
            client=self._controller.client,
            cache=self._evidence_scores,
        )
        ordered = order_evidence_for_state(evidence, scores) if scores else list(evidence)
        return await self._controller.assess_state(
            plan=plan,
            evidence=ordered,
            gate="assessment",
        )

    async def _call_inner(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        record_assessor_llm(skipped=False)
        return await self._inner.assess(plan, evidence)


class GatedResearchCompletenessReviewer:
    """Programmatic → Jev → optional LLM completeness reviewer."""

    def __init__(
        self,
        inner: ResearchCompletenessReviewer,
        controller: ResearchFastController | None = None,
    ) -> None:
        self._inner = inner
        self._controller = controller or ResearchFastController()

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
        if not research_jev_available() or can_review_programmatically(objective):
            return await self._inner.review(
                objective=objective,
                plan=plan,
                runtime_needs=runtime_needs,
                assessment=assessment,
                assessments=assessments,
                evidence=evidence,
                available_source_types=available_source_types,
            )
        jev_call = self._controller.assess_state(
            plan=plan,
            evidence=evidence,
            objective=objective,
            runtime_needs=runtime_needs,
            known_contradictions=assessment.contradictions if assessment else None,
            gate="completeness",
        )
        if research_jev_mode() == "shadow":
            decision, draft, latency_ms = await _parallel_shadow(
                jev_call,
                lambda: self._call_inner(
                    objective=objective, plan=plan, runtime_needs=runtime_needs,
                    assessment=assessment, assessments=assessments, evidence=evidence,
                    available_source_types=available_source_types,
                ),
            )
            _compare_completeness(decision, draft, llm_latency_ms=latency_ms)
            return draft
        decision = await jev_call
        if decision.mode == "active" and decision.would_short_circuit:
            record_completeness_llm(skipped=True)
            record_follow_up_wave_avoided()
            emit_jev_short_circuit(
                gate="completeness",
                mode=decision.mode,
                decision=decision.outcome,
                latency_ms=decision.latency_ms,
            )
            return ResearchCompletenessDraft(
                result="complete",
                rationale=COMPLETE_RATIONALE,
                missing_questions=[],
                considered_evidence_ids=[item.evidence_id for item in evidence],
                considered_question_keys=[row.question_key for row in runtime_needs],
                model_provider="jev",
                model_name=decision.model,
            )
        started = time.perf_counter()
        draft = await self._call_inner(
            objective=objective,
            plan=plan,
            runtime_needs=runtime_needs,
            assessment=assessment,
            assessments=assessments,
            evidence=evidence,
            available_source_types=available_source_types,
        )
        llm_latency_ms = (time.perf_counter() - started) * 1000
        _compare_completeness(decision, draft, llm_latency_ms=llm_latency_ms)
        return draft

    async def _call_inner(
        self,
        *,
        objective: ResearchObjective | None,
        plan: ResearchPlan,
        runtime_needs: Sequence[RuntimeResearchNeed],
        assessment: ResearchAssessmentDraft | None,
        assessments: Sequence[ResearchAssessmentDraft],
        evidence: Sequence[AssessableEvidence],
        available_source_types: Sequence[str] | None,
    ) -> ResearchCompletenessDraft:
        record_completeness_llm(skipped=False)
        return await self._inner.review(
            objective=objective,
            plan=plan,
            runtime_needs=runtime_needs,
            assessment=assessment,
            assessments=assessments,
            evidence=evidence,
            available_source_types=available_source_types,
        )


async def _timed_call[T](call: Callable[[], Awaitable[T]]) -> tuple[T, float]:
    started = time.perf_counter()
    result = await call()
    return result, (time.perf_counter() - started) * 1000


async def _parallel_shadow[T](
    jev_call: Awaitable[ResearchFastDecision], inner_call: Callable[[], Awaitable[T]],
) -> tuple[ResearchFastDecision, T, float]:
    """Independent shadow evaluation must not serialize the authoritative review."""
    jev_task = asyncio.ensure_future(jev_call)
    inner_task = asyncio.create_task(_timed_call(inner_call))
    try:
        decision, (draft, latency_ms) = await asyncio.gather(jev_task, inner_task)
        return decision, draft, latency_ms
    finally:
        # A failed/cancelled review must not leave billable network calls running.
        for task in (jev_task, inner_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(jev_task, inner_task, return_exceptions=True)


def wrap_research_assessor(inner: ResearchAssessor) -> ResearchAssessor:
    if not research_jev_available():
        return inner
    return GatedResearchAssessor(inner)


def wrap_completeness_reviewer(
    inner: ResearchCompletenessReviewer,
) -> ResearchCompletenessReviewer:
    if not research_jev_available():
        return inner
    return GatedResearchCompletenessReviewer(inner)


def _directional_agreement(jev_outcome: str, *, llm_positive: bool) -> bool:
    if jev_outcome == "sufficient":
        return llm_positive
    if jev_outcome == "insufficient":
        return not llm_positive
    return False


def _sufficient_draft(
    plan: ResearchPlan,
    evidence: Sequence[AssessableEvidence],
    decision: ResearchFastDecision,
) -> ResearchAssessmentDraft | None:
    """Only short-circuit when every need already has persisted found IDs."""
    need_rows: list[ResearchNeedAssessment] = []
    for need in plan.needs:
        supporting = found_evidence_ids(need.id, evidence)
        if not supporting:
            return None
        need_rows.append(
            ResearchNeedAssessment(
                research_need_id=need.id,
                sufficient=True,
                supporting_evidence_ids=supporting,
            )
        )
    return ResearchAssessmentDraft(
        result="sufficient",
        rationale=SUFFICIENT_RATIONALE,
        need_assessments=need_rows,
        gaps=[],
        contradictions=[],
        considered_evidence_ids=[item.evidence_id for item in evidence],
        model_provider="jev",
        model_name=decision.model,
    )


def _compare_assessment(
    decision: ResearchFastDecision,
    draft: ResearchAssessmentDraft,
    *,
    llm_latency_ms: float,
) -> None:
    llm_decision = draft.result
    jev_sufficient = decision.outcome == "sufficient"
    llm_sufficient = llm_decision == "sufficient"
    emit_jev_shadow_comparison(
        gate="assessment",
        mode=decision.mode,
        jev_decision=decision.outcome,
        llm_decision=llm_decision,
        agreement=_directional_agreement(
            decision.outcome, llm_positive=llm_sufficient
        ),
        would_have_short_circuited=decision.would_short_circuit,
        false_sufficient_candidate=jev_sufficient and not llm_sufficient,
        false_insufficient_candidate=decision.outcome == "insufficient" and llm_sufficient,
        jev_latency_ms=decision.latency_ms,
        llm_latency_ms=llm_latency_ms,
        estimated_avoided_llm_calls=1 if decision.would_short_circuit else 0,
        research_outcome=llm_decision,
        source_types=list(decision.source_types),
    )


def _compare_completeness(
    decision: ResearchFastDecision,
    draft: ResearchCompletenessDraft,
    *,
    llm_latency_ms: float,
) -> None:
    llm_decision = draft.result
    jev_complete = decision.outcome == "sufficient"
    llm_complete = llm_decision == "complete"
    emit_jev_shadow_comparison(
        gate="completeness",
        mode=decision.mode,
        jev_decision=decision.outcome,
        llm_decision=llm_decision,
        agreement=_directional_agreement(
            decision.outcome, llm_positive=llm_complete
        ),
        would_have_short_circuited=decision.would_short_circuit,
        false_sufficient_candidate=jev_complete and not llm_complete,
        false_insufficient_candidate=decision.outcome == "insufficient" and llm_complete,
        jev_latency_ms=decision.latency_ms,
        llm_latency_ms=llm_latency_ms,
        estimated_avoided_llm_calls=1 if decision.would_short_circuit else 0,
        research_outcome=llm_decision,
        source_types=list(decision.source_types),
    )
