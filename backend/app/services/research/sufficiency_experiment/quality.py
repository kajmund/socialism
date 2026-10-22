"""Gates that block SUFFICIENT unless reused quality + obligations allow it."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    GateInputs,
    NeedAggregation,
    QualityDecision,
)


def quality_gate(
    aggregations: Sequence[NeedAggregation],
    inputs: GateInputs,
    config: ExperimentConfig,
) -> QualityDecision:
    reasons: list[str] = []
    if inputs.span_coverage < 1.0:
        reasons.append("span_coverage_incomplete")
    if inputs.omitted_evidence_ids:
        reasons.append("evidence_omitted")
    if inputs.missing_evaluations:
        reasons.append("missing_evaluations")
    if inputs.evaluation_errors:
        reasons.append("evaluation_errors")
    if inputs.budget_exhausted:
        reasons.append("budget_exhausted")
    if any(row.unknown_requirements for row in aggregations):
        reasons.append("unknown_requirements")
    if any(row.unresolved_conflicts for row in aggregations):
        reasons.append("unresolved_conflicts")
    if not aggregations or not all(row.sufficient for row in aggregations):
        reasons.append("obligations_unverified")
    semantic = bool(aggregations) and all(
        all(state.verified for state in row.obligation_states)
        and not row.unknown_requirements
        for row in aggregations
    )
    allows = not reasons and semantic
    escalate = (
        not allows
        and not inputs.budget_exhausted
        and inputs.span_coverage == 1.0
        and not inputs.omitted_evidence_ids
        and not inputs.missing_evaluations
        and not inputs.evaluation_errors
        and inputs.narrative_rounds < config.max_narrative_depth
    )
    return QualityDecision(
        allows_sufficient=allows,
        escalate_permitted=escalate,
        applicable_subworkflows=(),
        reasons=tuple(reasons),
        span_coverage=inputs.span_coverage,
        semantic_complete=semantic,
        omitted_evidence_ids=tuple(inputs.omitted_evidence_ids),
        missing_evaluations=tuple(inputs.missing_evaluations),
        budget_exhausted=inputs.budget_exhausted,
    )
