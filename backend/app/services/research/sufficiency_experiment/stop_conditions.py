"""Shadow stop-point instrumentation. No execution change."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.sufficiency_experiment.types import (
    CoverageReport,
    ExperimentReport,
    NeedAggregation,
    PairEvaluation,
    StopOutcome,
    StopShadow,
)


def shadow_stop(
    *,
    pairs: Sequence[PairEvaluation],
    aggregations: Sequence[NeedAggregation],
    coverage: CoverageReport | None,
) -> StopShadow:
    unresolved_pairs = {
        frozenset(side.claim_id for side in conflict.sides if side.claim_id)
        for row in aggregations
        for conflict in row.conflicts
        if conflict.status == "unresolved" and len(conflict.sides) >= 2
    }
    relevance_verified = any(
        state.kind == "relevance" and state.verified
        for row in aggregations
        for state in row.obligation_states
    )
    for index, pair in enumerate(pairs):
        if pair.verdict != "CONTRADICTS":
            continue
        blocking = (
            frozenset((pair.left_claim_id, pair.right_claim_id)) in unresolved_pairs
            and relevance_verified
        )
        later = list(pairs[index + 1 :])
        return StopShadow(
            condition="conflict_confirmed",
            would_stop=blocking,
            conflict_id=pair.pair_id if blocking else None,
            pair_verdict=pair.verdict,
            remaining_pair_calls=len(later),
            estimated_calls_saved=len(later) + 1,
            estimated_latency_saved_ms=sum(item.latency_ms for item in later),
            coverage_complete=bool(coverage and coverage.gate_complete),
            blocking=blocking,
            risk=None if blocking else "conflict_not_blocking",
        )
    return StopShadow(
        condition="conflict_confirmed",
        would_stop=False,
        conflict_id=None,
        pair_verdict=None,
        remaining_pair_calls=0,
        estimated_calls_saved=0,
        estimated_latency_saved_ms=0.0,
        coverage_complete=bool(coverage and coverage.gate_complete),
        blocking=False,
        risk="no_conflict_pair",
    )


def stop_outcome(report: ExperimentReport) -> StopOutcome:
    existential = report.stop_mode == "existential"
    skipped = sum(
        1
        for pair in report.pairs
        if pair.status == "unevaluated" and pair.error == "stop_condition_met"
    )
    conflict = any(pair.verdict == "CONTRADICTS" for pair in report.pairs)
    return StopOutcome(
        goal="EXISTS_BLOCKING_CONFLICT" if existential else "EXHAUSTIVE",
        result="CONFLICT_FOUND" if conflict else "NONE",
        investigation_status="PARTIAL" if existential and skipped else "COMPLETE",
        evidence_status="VERIFIED" if report.status == "sufficient" else "UNVERIFIED",
    )
