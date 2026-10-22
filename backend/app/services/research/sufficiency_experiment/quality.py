"""Deterministic gates that decide whether a narrative pass may run."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    NeedAggregation,
    QualityDecision,
)


def quality_gate(
    aggregations: Sequence[NeedAggregation],
    *,
    coverage: float,
    omitted_evidence_ids: Sequence[str],
    recursion_depth: int,
    config: ExperimentConfig,
    jev_requires_narrative: bool,
) -> QualityDecision:
    reasons: list[str] = []
    if coverage < 1.0:
        reasons.append("coverage_incomplete")
    if omitted_evidence_ids:
        reasons.append("evidence_omitted")
    if recursion_depth >= config.max_narrative_depth:
        reasons.append("recursion_limit")
    if not jev_requires_narrative:
        reasons.append("jev_not_required")
    if not any(row.needs_narrative for row in aggregations):
        reasons.append("no_undecided_outcome")
    escalate = not reasons
    return QualityDecision(
        escalate=escalate,
        reasons=tuple(reasons),
        coverage=coverage,
        omitted_evidence_ids=tuple(omitted_evidence_ids),
        recursion_depth=recursion_depth,
    )
