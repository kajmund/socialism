"""Research-specific ELK events and in-flight counters."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Iterator, Literal

from app.observability.events import EVENT_DATASET_RESEARCH, log_event

logger = logging.getLogger("app.research.observability")

ResearchJevMode = Literal["shadow", "active"]
ResearchJevDecision = Literal["sufficient", "insufficient", "uncertain", "error"]
ResearchJevErrorCategory = Literal[
    "timeout",
    "auth",
    "rate_limit",
    "invalid_response",
    "schema_validation",
    "transport",
    "unknown",
]

EVENT_JEV_ASSESSMENT_STARTED = "research.jev.assessment.started"
EVENT_JEV_ASSESSMENT_COMPLETED = "research.jev.assessment.completed"
EVENT_JEV_ASSESSMENT_FAILED = "research.jev.assessment.failed"
EVENT_JEV_COMPLETENESS_STARTED = "research.jev.completeness.started"
EVENT_JEV_COMPLETENESS_COMPLETED = "research.jev.completeness.completed"
EVENT_JEV_COMPLETENESS_FAILED = "research.jev.completeness.failed"
EVENT_JEV_EVIDENCE_SCORED = "research.jev.evidence_scored"
EVENT_JEV_SHADOW_COMPARISON = "research.jev.shadow_comparison"
EVENT_JEV_SHORT_CIRCUIT = "research.jev.short_circuit"
EVENT_RESEARCH_EXECUTION_SUMMARY = "research.execution.summary"


@dataclass
class ResearchObsStats:
    started_at: float = field(default_factory=time.perf_counter)
    jev_call_count: int = 0
    jev_total_latency_ms: float = 0.0
    assessor_llm_calls: int = 0
    completeness_llm_calls: int = 0
    assessor_llm_skipped: int = 0
    completeness_llm_skipped: int = 0
    follow_up_waves_avoided: int = 0
    evidence_count: int = 0
    provider_calls: int | None = None
    retrieval_calls: int | None = None


_stats: ContextVar[ResearchObsStats | None] = ContextVar(
    "research_obs_stats", default=None
)


def current_research_stats() -> ResearchObsStats | None:
    return _stats.get()


def bind_research_stats(stats: ResearchObsStats | None) -> Token[ResearchObsStats | None]:
    return _stats.set(stats)


def reset_research_stats(token: Token[ResearchObsStats | None]) -> None:
    _stats.reset(token)


@contextmanager
def research_obs_scope() -> Iterator[ResearchObsStats]:
    stats = ResearchObsStats()
    token = bind_research_stats(stats)
    try:
        yield stats
    finally:
        reset_research_stats(token)


def record_jev_call(latency_ms: float) -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.jev_call_count += 1
    stats.jev_total_latency_ms += latency_ms


def record_assessor_llm(*, skipped: bool) -> None:
    stats = _stats.get()
    if stats is None:
        return
    if skipped:
        stats.assessor_llm_skipped += 1
    else:
        stats.assessor_llm_calls += 1


def record_completeness_llm(*, skipped: bool) -> None:
    stats = _stats.get()
    if stats is None:
        return
    if skipped:
        stats.completeness_llm_skipped += 1
    else:
        stats.completeness_llm_calls += 1


def record_follow_up_wave_avoided() -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.follow_up_waves_avoided += 1


def record_evidence_count(count: int) -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.evidence_count = max(stats.evidence_count, count)


def _log_research_event(
    event_name: str,
    *,
    outcome: str,
    duration_ms: float | None = None,
    fields: dict[str, object] | None = None,
    level: int = logging.INFO,
) -> None:
    log_event(
        logger,
        event_name,
        dataset=EVENT_DATASET_RESEARCH,
        outcome=outcome,
        duration_ms=duration_ms,
        fields=fields,
        level=level,
    )


def emit_jev_started(
    *,
    event_name: str,
    mode: ResearchJevMode,
    model: str,
    provider: str,
    input_chars: int,
    input_sha256: str,
    evidence_count: int,
    source_types: list[str],
) -> None:
    _log_research_event(
        event_name,
        outcome="unknown",
        fields={
            "jev": {
                "provider": provider,
                "model": model,
                "mode": mode,
                "input_chars": input_chars,
                "input_sha256": input_sha256,
            },
            "research": {
                "evidence_count": evidence_count,
                "source_types": source_types,
            },
        },
    )


def emit_jev_decision(
    *,
    event_name: str,
    outcome: str,
    mode: ResearchJevMode,
    model: str,
    provider: str,
    decision: ResearchJevDecision,
    answerable_now_probability: float | None,
    material_gap_probability: float | None,
    contradiction_probability: float | None,
    follow_up_change_probability: float | None,
    additional_source_probability: float | None,
    decision_confidence: float | None,
    sufficient_threshold: float,
    incomplete_threshold: float,
    confidence_threshold: float,
    latency_ms: float,
    input_chars: int,
    input_sha256: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    fallback_used: bool,
    fallback_reason: str | None,
    error_category: ResearchJevErrorCategory | None = None,
    evidence_count: int | None = None,
    source_types: list[str] | None = None,
) -> None:
    jev: dict[str, object] = {
        "provider": provider,
        "model": model,
        "mode": mode,
        "decision": decision,
        "decision_confidence": decision_confidence,
        "sufficient_threshold": sufficient_threshold,
        "incomplete_threshold": incomplete_threshold,
        "confidence_threshold": confidence_threshold,
        "latency_ms": latency_ms,
        "input_chars": input_chars,
        "input_sha256": input_sha256,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
    }
    if answerable_now_probability is not None:
        jev["answerable_now_probability"] = answerable_now_probability
    if material_gap_probability is not None:
        jev["material_gap_probability"] = material_gap_probability
    if contradiction_probability is not None:
        jev["contradiction_probability"] = contradiction_probability
    if follow_up_change_probability is not None:
        jev["follow_up_change_probability"] = follow_up_change_probability
    if additional_source_probability is not None:
        jev["additional_source_probability"] = additional_source_probability
    if prompt_tokens is not None:
        jev["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        jev["completion_tokens"] = completion_tokens
    if total_tokens is not None:
        jev["total_tokens"] = total_tokens
    if error_category is not None:
        jev["error_category"] = error_category
    research: dict[str, object] = {}
    if evidence_count is not None:
        research["evidence_count"] = evidence_count
    if source_types:
        research["source_types"] = source_types
    fields: dict[str, object] = {"jev": jev}
    if research:
        fields["research"] = research
    _log_research_event(
        event_name,
        outcome=outcome,
        duration_ms=latency_ms,
        fields=fields,
        level=logging.WARNING if decision == "error" else logging.INFO,
    )


def emit_jev_shadow_comparison(
    *,
    gate: str,
    mode: ResearchJevMode,
    jev_decision: ResearchJevDecision,
    llm_decision: str,
    agreement: bool,
    would_have_short_circuited: bool,
    false_sufficient_candidate: bool,
    false_insufficient_candidate: bool,
    jev_latency_ms: float,
    llm_latency_ms: float,
    estimated_avoided_llm_calls: int,
    research_outcome: str | None,
    source_types: list[str],
) -> None:
    _log_research_event(
        EVENT_JEV_SHADOW_COMPARISON,
        outcome="success",
        fields={
            "jev": {
                "mode": mode,
                "decision": jev_decision,
                "latency_ms": jev_latency_ms,
            },
            "research": {
                "gate": gate,
                "llm_decision": llm_decision,
                "agreement": agreement,
                "would_have_short_circuited": would_have_short_circuited,
                "false_sufficient_candidate": false_sufficient_candidate,
                "false_insufficient_candidate": false_insufficient_candidate,
                "llm_latency_ms": llm_latency_ms,
                "estimated_avoided_llm_calls": estimated_avoided_llm_calls,
                "research_outcome": research_outcome,
                "source_types": source_types,
            },
        },
    )


def emit_jev_short_circuit(
    *,
    gate: str,
    mode: ResearchJevMode,
    decision: ResearchJevDecision,
    latency_ms: float,
) -> None:
    _log_research_event(
        EVENT_JEV_SHORT_CIRCUIT,
        outcome="success",
        duration_ms=latency_ms,
        fields={
            "jev": {"mode": mode, "decision": decision, "latency_ms": latency_ms},
            "research": {"gate": gate, "llm_skipped": True},
        },
    )


def emit_jev_evidence_scored(
    *,
    mode: ResearchJevMode,
    model: str,
    provider: str,
    evidence_id: str,
    source_type: str,
    content_hash: str,
    latency_ms: float,
    scores: dict[str, float],
    input_chars: int,
) -> None:
    _log_research_event(
        EVENT_JEV_EVIDENCE_SCORED,
        outcome="success",
        duration_ms=latency_ms,
        fields={
            "jev": {
                "provider": provider,
                "model": model,
                "mode": mode,
                "latency_ms": latency_ms,
                "input_chars": input_chars,
                **scores,
            },
            "research": {
                "evidence_id": evidence_id,
                "source_type": source_type,
                "evidence_hash": content_hash,
            },
        },
    )


def emit_research_execution_summary(
    *,
    stats: ResearchObsStats,
    final_status: str,
    total_waves: int,
    mode: ResearchJevMode | None,
) -> None:
    elapsed_ms = (time.perf_counter() - stats.started_at) * 1000
    research: dict[str, object] = {
        "elapsed_ms": elapsed_ms,
        "total_waves": total_waves,
        "llm_call_count": stats.assessor_llm_calls + stats.completeness_llm_calls,
        "jev_call_count": stats.jev_call_count,
        "jev_total_latency_ms": stats.jev_total_latency_ms,
        "assessor_llm_skipped": stats.assessor_llm_skipped,
        "completeness_llm_skipped": stats.completeness_llm_skipped,
        "follow_up_waves_avoided": stats.follow_up_waves_avoided,
        "evidence_count": stats.evidence_count,
        "final_status": final_status,
        "jev_mode": mode,
    }
    if stats.provider_calls is not None:
        research["provider_calls"] = stats.provider_calls
    if stats.retrieval_calls is not None:
        research["retrieval_calls"] = stats.retrieval_calls
    _log_research_event(
        EVENT_RESEARCH_EXECUTION_SUMMARY,
        outcome="success" if final_status in {"ready", "completed"} else "failure",
        duration_ms=elapsed_ms,
        fields={"research": research},
    )
