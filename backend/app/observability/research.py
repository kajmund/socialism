"""Research-specific ELK events and in-flight counters."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Literal, Self

from app.observability.events import EVENT_DATASET_RESEARCH, log_event

logger = logging.getLogger("app.research.observability")

ResearchJevMode = Literal["shadow", "active"]
ResearchJevDecision = Literal["sufficient", "insufficient", "uncertain", "error"]
ResearchJevErrorCategory = Literal[
    "timeout",
    "auth",
    "rate_limit",
    "invalid_request",
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
    jev_evaluation_requested: int = 0
    jev_evaluation_executed: int = 0
    jev_evaluation_reused: int = 0
    jev_evaluation_singleflight_join: int = 0
    jev_evaluation_failed: int = 0
    jev_queue_wait_ms: float = 0.0
    jev_cache_lookup_ms: float = 0.0
    jev_singleflight_wait_ms: float = 0.0
    jev_http_ms: float = 0.0
    jev_parse_ms: float = 0.0
    jev_persistence_ms: float = 0.0
    jev_evaluation_ms: float = 0.0
    graph_revalidation_candidates: int = 0
    graph_revalidation_skipped: int = 0
    graph_revalidation_jev_required: int = 0
    graph_revalidation_completed: int = 0
    graph_revalidation_total_ms: float = 0.0
    graph_revalidation_lookup_ms: float = 0.0
    graph_revalidation_jev_ms: float = 0.0
    graph_revalidation_persistence_ms: float = 0.0
    provider_queue_wait_ms: float = 0.0
    provider_fetch_ms: float = 0.0
    provider_parse_ms: float = 0.0
    provider_ingest_ms: float = 0.0
    provider_graph_revalidation_ms: float = 0.0
    provider_graph_revalidation_enqueue_ms: float = 0.0
    provider_persist_ms: float = 0.0
    provider_total_ms: float = 0.0
    db_connection_checkout_ms: float = 0.0
    db_connection_checkout_total_ms: float = 0.0
    db_connection_checkout_count: int = 0
    assessor_llm_calls: int = 0
    completeness_llm_calls: int = 0
    assessor_llm_skipped: int = 0
    completeness_llm_skipped: int = 0
    follow_up_waves_avoided: int = 0
    evidence_count: int = 0
    provider_calls: int | None = None
    retrieval_calls: int | None = None
    question_step_counts: dict[str, int] = field(default_factory=dict)
    question_step_duration_ms: dict[str, float] = field(default_factory=dict)
    question_step_models: dict[str, set[str]] = field(default_factory=dict)
    decomposition_exhausted_total: int = 0
    decomposition_exhausted_redundancy_total: int = 0
    research_fallback_started_total: int = 0
    research_fallback_sufficient_total: int = 0
    research_fallback_insufficient_total: int = 0
    research_fallback_failed_total: int = 0
    unresolved_required_question_count: int = 0
    not_required_question_count: int = 0


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
    """Outbound JEV call. Prefer ``record_jev_evaluation(executed=1)`` for new code."""
    stats = _stats.get()
    if stats is None:
        return
    stats.jev_call_count += 1
    stats.jev_total_latency_ms += latency_ms


def record_jev_evaluation(
    *,
    requested: int = 0,
    executed: int = 0,
    reused: int = 0,
    singleflight_join: int = 0,
    failed: int = 0,
    queue_wait_ms: float = 0.0,
    cache_lookup_ms: float = 0.0,
    singleflight_wait_ms: float = 0.0,
    http_ms: float = 0.0,
    parse_ms: float = 0.0,
    persistence_ms: float = 0.0,
    total_ms: float = 0.0,
) -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.jev_evaluation_requested += requested
    stats.jev_evaluation_executed += executed
    stats.jev_evaluation_reused += reused
    stats.jev_evaluation_singleflight_join += singleflight_join
    stats.jev_evaluation_failed += failed
    stats.jev_queue_wait_ms += queue_wait_ms
    stats.jev_cache_lookup_ms += cache_lookup_ms
    stats.jev_singleflight_wait_ms += singleflight_wait_ms
    stats.jev_http_ms += http_ms
    stats.jev_parse_ms += parse_ms
    stats.jev_persistence_ms += persistence_ms
    stats.jev_evaluation_ms += total_ms
    if executed:
        stats.jev_call_count += executed
        stats.jev_total_latency_ms += http_ms


def record_graph_revalidation(
    *,
    candidates: int = 0,
    skipped: int = 0,
    jev_required: int = 0,
    completed: int = 0,
    total_ms: float = 0.0,
    lookup_ms: float = 0.0,
    jev_ms: float = 0.0,
    persistence_ms: float = 0.0,
) -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.graph_revalidation_candidates += candidates
    stats.graph_revalidation_skipped += skipped
    stats.graph_revalidation_jev_required += jev_required
    stats.graph_revalidation_completed += completed
    stats.graph_revalidation_total_ms += total_ms
    stats.graph_revalidation_lookup_ms += lookup_ms
    stats.graph_revalidation_jev_ms += jev_ms
    stats.graph_revalidation_persistence_ms += persistence_ms


_PROVIDER_PHASE_FIELDS = {
    "queue_wait": "provider_queue_wait_ms",
    "fetch": "provider_fetch_ms",
    "parse": "provider_parse_ms",
    "ingest": "provider_ingest_ms",
    "graph_revalidation": "provider_graph_revalidation_ms",
    "graph_revalidation_enqueue": "provider_graph_revalidation_enqueue_ms",
    "persist": "provider_persist_ms",
    "total": "provider_total_ms",
}


def record_db_connection_checkout(duration_ms: float) -> None:
    """Longest checkout in this attempt, plus the sum. No-op outside research."""
    stats = _stats.get()
    if stats is None:
        return
    stats.db_connection_checkout_count += 1
    stats.db_connection_checkout_total_ms += duration_ms
    stats.db_connection_checkout_ms = max(stats.db_connection_checkout_ms, duration_ms)


def record_provider_phase(name: str, duration_ms: float) -> None:
    field = _PROVIDER_PHASE_FIELDS.get(name)
    if field is None:
        raise ValueError(f"unknown provider phase: {name}")
    stats = _stats.get()
    if stats is None:
        return
    setattr(stats, field, getattr(stats, field) + duration_ms)
    record_question_step(f"provider_{name}", duration_ms=duration_ms)


class ProviderPhase:
    """Accumulate one provider phase, including time spent awaiting I/O."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._started = 0.0

    def __enter__(self) -> Self:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_exc: object) -> None:
        record_provider_phase(self.name, (time.perf_counter() - self._started) * 1000)


def record_decomposition_exhausted(*, redundancy: bool) -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.decomposition_exhausted_total += 1
    if redundancy:
        stats.decomposition_exhausted_redundancy_total += 1


def record_research_fallback(
    outcome: Literal["started", "sufficient", "insufficient", "failed"],
) -> None:
    stats = _stats.get()
    if stats is None:
        return
    if outcome == "started":
        stats.research_fallback_started_total += 1
    elif outcome == "sufficient":
        stats.research_fallback_sufficient_total += 1
    elif outcome == "insufficient":
        stats.research_fallback_insufficient_total += 1
    else:
        stats.research_fallback_failed_total += 1


def record_question_outcome_counts(*, unresolved_required: int, not_required: int) -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.unresolved_required_question_count = unresolved_required
    stats.not_required_question_count = not_required


def record_question_step(
    step: str,
    *,
    duration_ms: float,
    model_provider: str = "",
    model: str = "",
) -> None:
    stats = _stats.get()
    if stats is None:
        return
    stats.question_step_counts[step] = stats.question_step_counts.get(step, 0) + 1
    stats.question_step_duration_ms[step] = (
        stats.question_step_duration_ms.get(step, 0.0) + duration_ms
    )
    identity = ":".join(part for part in (model_provider, model) if part)
    if identity:
        stats.question_step_models.setdefault(step, set()).add(identity)


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
        "jev_evaluation_requested_total": stats.jev_evaluation_requested,
        "jev_evaluation_executed_total": stats.jev_evaluation_executed,
        "jev_evaluation_reused_total": stats.jev_evaluation_reused,
        "jev_evaluation_singleflight_join_total": stats.jev_evaluation_singleflight_join,
        "jev_evaluation_failed_total": stats.jev_evaluation_failed,
        "jev_queue_wait_ms": stats.jev_queue_wait_ms,
        "jev_cache_lookup_ms": stats.jev_cache_lookup_ms,
        "jev_singleflight_wait_ms": stats.jev_singleflight_wait_ms,
        "jev_http_ms": stats.jev_http_ms,
        "jev_parse_ms": stats.jev_parse_ms,
        "jev_persistence_ms": stats.jev_persistence_ms,
        "jev_evaluation_ms": stats.jev_evaluation_ms,
        "graph_revalidation_candidate_total": stats.graph_revalidation_candidates,
        "graph_revalidation_skipped_processed_total": stats.graph_revalidation_skipped,
        "graph_revalidation_jev_required_total": stats.graph_revalidation_jev_required,
        "graph_revalidation_completed_total": stats.graph_revalidation_completed,
        "graph_revalidation_total_ms": stats.graph_revalidation_total_ms,
        "graph_revalidation_lookup_ms": stats.graph_revalidation_lookup_ms,
        "graph_revalidation_jev_ms": stats.graph_revalidation_jev_ms,
        "graph_revalidation_persistence_ms": stats.graph_revalidation_persistence_ms,
        "provider_queue_wait_ms": stats.provider_queue_wait_ms,
        "provider_fetch_ms": stats.provider_fetch_ms,
        "provider_parse_ms": stats.provider_parse_ms,
        "provider_ingest_ms": stats.provider_ingest_ms,
        "provider_graph_revalidation_ms": stats.provider_graph_revalidation_ms,
        "provider_graph_revalidation_enqueue_ms": stats.provider_graph_revalidation_enqueue_ms,
        "provider_persist_ms": stats.provider_persist_ms,
        "provider_total_ms": stats.provider_total_ms,
        "db_connection_checkout_ms": stats.db_connection_checkout_ms,
        "db_connection_checkout_total_ms": stats.db_connection_checkout_total_ms,
        "db_connection_checkout_count": stats.db_connection_checkout_count,
        "assessor_llm_skipped": stats.assessor_llm_skipped,
        "completeness_llm_skipped": stats.completeness_llm_skipped,
        "follow_up_waves_avoided": stats.follow_up_waves_avoided,
        "evidence_count": stats.evidence_count,
        "final_status": final_status,
        "jev_mode": mode,
        "decomposition_exhausted_total": stats.decomposition_exhausted_total,
        "decomposition_exhausted_redundancy_total": stats.decomposition_exhausted_redundancy_total,
        "research_fallback_started_total": stats.research_fallback_started_total,
        "research_fallback_sufficient_total": stats.research_fallback_sufficient_total,
        "research_fallback_insufficient_total": stats.research_fallback_insufficient_total,
        "research_fallback_failed_total": stats.research_fallback_failed_total,
        "unresolved_required_question_count": stats.unresolved_required_question_count,
        "not_required_question_count": stats.not_required_question_count,
        "question_steps": {
            step: {
                "count": count,
                "duration_ms": stats.question_step_duration_ms.get(step, 0.0),
                "models": sorted(stats.question_step_models.get(step, set())),
            }
            for step, count in stats.question_step_counts.items()
        },
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
