"""Jev-backed research control decisions. Does not retrieve or write evidence."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.config import settings
from app.jev.system import (
    HttpJevSystemOne,
    JevClientError,
    JevSystemOne,
    JevSystemOneResult,
    classify_jev_error,
    noul_confidence,
    parse_noul,
)
from app.observability.research import (
    EVENT_JEV_ASSESSMENT_COMPLETED,
    EVENT_JEV_ASSESSMENT_FAILED,
    EVENT_JEV_ASSESSMENT_STARTED,
    EVENT_JEV_COMPLETENESS_COMPLETED,
    EVENT_JEV_COMPLETENESS_FAILED,
    EVENT_JEV_COMPLETENESS_STARTED,
    ResearchJevDecision,
    ResearchJevErrorCategory,
    ResearchJevMode,
    emit_jev_decision,
    emit_jev_started,
    record_evidence_count,
    record_jev_call,
)
from app.services.research.assessment import AssessableEvidence
from app.services.research.fast_state import (
    CompactResearchState,
    compact_research_state,
    objective_text,
)
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchPlan
from app.services.research.planner import ResearchObjective

JEV_PROVIDER = "jev"
ResearchFastGate = Literal["assessment", "completeness"]


@dataclass(frozen=True)
class ResearchFastDecision:
    outcome: ResearchJevDecision
    answerable_now_probability: float | None
    material_gap_probability: float | None
    contradiction_probability: float | None
    follow_up_change_probability: float | None
    additional_source_probability: float | None
    confidence: float | None
    mode: ResearchJevMode
    model: str
    latency_ms: float
    input_chars: int
    input_sha256: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    fallback_used: bool
    fallback_reason: str | None
    error_category: ResearchJevErrorCategory | None
    would_short_circuit: bool
    source_types: tuple[str, ...]
    evidence_count: int

    @property
    def is_error(self) -> bool:
        return self.outcome == "error"


def research_jev_available() -> bool:
    return bool(settings.research_jev_enabled and settings.typesafe_api_key.strip())


def research_jev_mode() -> ResearchJevMode:
    mode = settings.research_jev_mode
    if mode in {"shadow", "active"}:
        return mode
    return "shadow"


def research_jev_model() -> str:
    override = settings.research_jev_model.strip()
    return override or settings.jev_model


def _noul_question(instructions: str, *, true: str, false: str) -> dict[str, Any]:
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": true, "false": false},
    }


ASSESSMENT_QUESTIONS: dict[str, Any] = {
    "answerable_now": _noul_question(
        "Is the research question already answerable from the supplied evidence?",
        true="The evidence is enough to answer the question now.",
        false="Important information is still missing.",
    ),
    "material_gap": _noul_question(
        "Is there a material gap that still blocks a reliable answer?",
        true="A missing fact or source would change the answer.",
        false="Remaining gaps are minor or already covered.",
    ),
    "contradiction": _noul_question(
        "Do the sources materially contradict each other on the question?",
        true="There is a contradiction that must be resolved.",
        false="Sources are consistent enough to proceed.",
    ),
    "follow_up_change": _noul_question(
        "Would another research wave likely change the answer?",
        true="More retrieval would likely change the conclusion.",
        false="Another wave is unlikely to change the answer.",
    ),
    "additional_source": _noul_question(
        "Is an additional source type still required?",
        true="A different source type is still needed.",
        false="Current source types are enough.",
    ),
}

COMPLETENESS_QUESTIONS: dict[str, Any] = {
    "answerable_now": _noul_question(
        "Is the original research objective materially covered?",
        true="The objective is covered by the current questions and evidence.",
        false="An important part of the objective is still unanswered.",
    ),
    "material_gap": _noul_question(
        "Is an important unanswered aspect of the objective still present?",
        true="A material aspect of the objective was never asked.",
        false="Known questions already cover the objective.",
    ),
    "follow_up_change": _noul_question(
        "Would another research wave likely change the answer to the objective?",
        true="Another wave would likely change the answer.",
        false="Another wave is unlikely to change the answer.",
    ),
    "additional_source": _noul_question(
        "Is evidence diversity or source coverage materially insufficient?",
        true="Source coverage is too narrow for the objective.",
        false="Source coverage is materially sufficient.",
    ),
    "contradiction": _noul_question(
        "Do unresolved contradictions still prevent treating the objective as complete?",
        true="Contradictions still block completion.",
        false="No material contradiction remains.",
    ),
}


class ResearchFastController:
    """One System One request per research state. Bounded Noul questions only."""

    def __init__(self, client: JevSystemOne | None = None) -> None:
        self.client = client or HttpJevSystemOne()

    async def assess_state(
        self,
        *,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
        objective: ResearchObjective | None = None,
        runtime_needs: Sequence[RuntimeResearchNeed] | None = None,
        known_contradictions: Sequence[str] | None = None,
        gate: ResearchFastGate = "assessment",
    ) -> ResearchFastDecision:
        mode = research_jev_mode()
        model = research_jev_model()
        state = compact_research_state(
            objective=objective_text(objective=objective, plan=plan),
            plan=plan,
            evidence=evidence,
            runtime_needs=runtime_needs,
            known_contradictions=known_contradictions,
            max_evidence_items=settings.research_jev_max_evidence_items,
            max_state_chars=settings.research_jev_max_state_chars,
        )
        record_evidence_count(state.evidence_count)
        questions = ASSESSMENT_QUESTIONS if gate == "assessment" else COMPLETENESS_QUESTIONS
        started_event = (
            EVENT_JEV_ASSESSMENT_STARTED
            if gate == "assessment"
            else EVENT_JEV_COMPLETENESS_STARTED
        )
        completed_event = (
            EVENT_JEV_ASSESSMENT_COMPLETED
            if gate == "assessment"
            else EVENT_JEV_COMPLETENESS_COMPLETED
        )
        failed_event = (
            EVENT_JEV_ASSESSMENT_FAILED
            if gate == "assessment"
            else EVENT_JEV_COMPLETENESS_FAILED
        )
        emit_jev_started(
            event_name=started_event,
            mode=mode,
            model=model,
            provider=JEV_PROVIDER,
            input_chars=state.input_chars,
            input_sha256=state.input_sha256,
            evidence_count=state.evidence_count,
            source_types=list(state.source_types),
        )
        started = time.perf_counter()
        try:
            result = await self.client.ask(
                state=state.payload,
                questions=questions,
                model=model,
                timeout_seconds=settings.research_jev_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - Jev failure must fall back to LLM
            decision = _error_decision(
                exc,
                mode=mode,
                model=model,
                state=state,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            record_jev_call(decision.latency_ms)
            _emit_decision(failed_event, decision, outcome="failure")
            return decision
        try:
            decision = _decision_from_result(result, mode=mode, state=state)
        except Exception as exc:  # noqa: BLE001 - invalid Jev payload falls back
            decision = _error_decision(
                exc,
                mode=mode,
                model=result.model,
                state=state,
                latency_ms=result.latency_ms,
            )
            record_jev_call(decision.latency_ms)
            _emit_decision(failed_event, decision, outcome="failure")
            return decision
        record_jev_call(decision.latency_ms)
        _emit_decision(completed_event, decision, outcome="success")
        return decision


def _decision_from_result(
    result: JevSystemOneResult,
    *,
    mode: ResearchJevMode,
    state: CompactResearchState,
) -> ResearchFastDecision:
    answerable = parse_noul(result.answers, "answerable_now")
    gap = parse_noul(result.answers, "material_gap")
    contradiction = parse_noul(result.answers, "contradiction")
    follow_up = parse_noul(result.answers, "follow_up_change")
    additional = parse_noul(result.answers, "additional_source")
    confidence = min(
        noul_confidence(answerable),
        noul_confidence(gap),
        noul_confidence(contradiction),
        noul_confidence(follow_up),
        noul_confidence(additional),
    )
    outcome = classify_research_decision(
        answerable_now=answerable,
        material_gap=gap,
        contradiction=contradiction,
        follow_up_change=follow_up,
        additional_source=additional,
        confidence=confidence,
        sufficient_threshold=settings.research_jev_sufficient_threshold,
        incomplete_threshold=settings.research_jev_incomplete_threshold,
        confidence_threshold=settings.research_jev_confidence_threshold,
    )
    would_short_circuit = outcome == "sufficient"
    fallback_used = False
    fallback_reason = None
    if mode == "shadow":
        fallback_used = True
        fallback_reason = "shadow_mode"
    elif outcome == "uncertain":
        fallback_used = True
        fallback_reason = "uncertain"
    elif outcome == "insufficient":
        fallback_used = True
        fallback_reason = "insufficient_needs_text"
    return ResearchFastDecision(
        outcome=outcome,
        answerable_now_probability=answerable,
        material_gap_probability=gap,
        contradiction_probability=contradiction,
        follow_up_change_probability=follow_up,
        additional_source_probability=additional,
        confidence=confidence,
        mode=mode,
        model=result.model,
        latency_ms=result.latency_ms,
        input_chars=state.input_chars,
        input_sha256=state.input_sha256,
        prompt_tokens=result.usage.prompt_tokens,
        completion_tokens=result.usage.completion_tokens,
        total_tokens=result.usage.total_tokens,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        error_category=None,
        would_short_circuit=would_short_circuit,
        source_types=state.source_types,
        evidence_count=state.evidence_count,
    )


def classify_research_decision(
    *,
    answerable_now: float,
    material_gap: float,
    contradiction: float,
    follow_up_change: float,
    additional_source: float,
    confidence: float,
    sufficient_threshold: float,
    incomplete_threshold: float,
    confidence_threshold: float,
) -> ResearchJevDecision:
    risk_ceiling = 1.0 - sufficient_threshold
    if (
        confidence >= confidence_threshold
        and answerable_now >= sufficient_threshold
        and material_gap <= risk_ceiling
        and contradiction <= risk_ceiling
        and follow_up_change <= risk_ceiling
        and additional_source <= risk_ceiling
    ):
        return "sufficient"
    if confidence >= confidence_threshold and (
        material_gap >= incomplete_threshold
        or answerable_now <= (1.0 - incomplete_threshold)
    ):
        return "insufficient"
    return "uncertain"


def _error_decision(
    exc: BaseException,
    *,
    mode: ResearchJevMode,
    model: str,
    state: CompactResearchState,
    latency_ms: float,
) -> ResearchFastDecision:
    category = classify_jev_error(exc)
    if isinstance(exc, JevClientError):
        category = exc.category
    return ResearchFastDecision(
        outcome="error",
        answerable_now_probability=None,
        material_gap_probability=None,
        contradiction_probability=None,
        follow_up_change_probability=None,
        additional_source_probability=None,
        confidence=None,
        mode=mode,
        model=model,
        latency_ms=latency_ms,
        input_chars=state.input_chars,
        input_sha256=state.input_sha256,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        fallback_used=True,
        fallback_reason=category,
        error_category=category,
        would_short_circuit=False,
        source_types=state.source_types,
        evidence_count=state.evidence_count,
    )


def _emit_decision(
    event_name: str, decision: ResearchFastDecision, *, outcome: str
) -> None:
    emit_jev_decision(
        event_name=event_name,
        outcome=outcome,
        mode=decision.mode,
        model=decision.model,
        provider=JEV_PROVIDER,
        decision=decision.outcome,
        answerable_now_probability=decision.answerable_now_probability,
        material_gap_probability=decision.material_gap_probability,
        contradiction_probability=decision.contradiction_probability,
        follow_up_change_probability=decision.follow_up_change_probability,
        additional_source_probability=decision.additional_source_probability,
        decision_confidence=decision.confidence,
        sufficient_threshold=settings.research_jev_sufficient_threshold,
        incomplete_threshold=settings.research_jev_incomplete_threshold,
        confidence_threshold=settings.research_jev_confidence_threshold,
        latency_ms=decision.latency_ms,
        input_chars=decision.input_chars,
        input_sha256=decision.input_sha256,
        prompt_tokens=decision.prompt_tokens,
        completion_tokens=decision.completion_tokens,
        total_tokens=decision.total_tokens,
        fallback_used=decision.fallback_used,
        fallback_reason=decision.fallback_reason,
        error_category=decision.error_category,
        evidence_count=decision.evidence_count,
        source_types=list(decision.source_types),
    )
