"""Machine-readable reasons behind the final decision. Additive only."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.sufficiency_experiment.types import (
    DecisionDiagnostics,
    DecisionReason,
    ExperimentReport,
    ExperimentStatus,
    NeedAggregation,
    QualityDecision,
    CoverageReport,
)


def decision_diagnostics(
    *,
    status: ExperimentStatus,
    draft_result: str,
    quality: QualityDecision | None,
    aggregations: Sequence[NeedAggregation],
    coverage: CoverageReport | None,
    technical_failures: Sequence[str],
    pair_unevaluated: bool,
) -> DecisionDiagnostics:
    unique_conflicts = tuple(
        dict.fromkeys(
            conflict_id
            for row in aggregations
            for conflict_id in row.unresolved_conflicts
        )
    )
    coverage_incomplete = coverage is not None and not coverage.gate_complete
    technical = bool(technical_failures or pair_unevaluated)
    support_incomplete = bool(
        quality is None
        or not quality.allows_sufficient
        or any(not row.sufficient for row in aggregations)
    )
    reasons: list[DecisionReason] = []
    if unique_conflicts:
        reasons.append("CONTRADICTION_FOUND")
    if coverage_incomplete:
        reasons.append("COVERAGE_INCOMPLETE")
    if support_incomplete and not coverage_incomplete and not unique_conflicts:
        reasons.append("SUPPORT_INCOMPLETE")
    elif support_incomplete and not (coverage_incomplete or unique_conflicts or technical):
        reasons.append("SUPPORT_INCOMPLETE")
    if technical:
        reasons.append("TECHNICAL_FAILURE")
    if (
        draft_result == "sufficient"
        and status == "sufficient"
        and quality is not None
        and quality.allows_sufficient
        and not reasons
    ):
        reasons.append("SUFFICIENT")
    if not reasons:
        reasons.append("SUPPORT_INCOMPLETE")
    return DecisionDiagnostics(reasons=tuple(reasons), unique_conflicts=unique_conflicts)


def decision_diagnostics_from_report(report: ExperimentReport) -> DecisionDiagnostics:
    return decision_diagnostics(
        status=report.status,
        draft_result=report.draft.result,
        quality=report.quality,
        aggregations=report.aggregations,
        coverage=report.coverage_report,
        technical_failures=(
            ((report.failure_mode,) if report.failure_mode else ())
            + tuple(row.job_id for row in report.evaluations if row.error)
        ),
        pair_unevaluated=bool(
            report.pair_coverage and report.pair_coverage.unevaluated
        ),
    )
