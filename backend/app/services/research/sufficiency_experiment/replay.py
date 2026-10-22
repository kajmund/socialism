"""Counterfactual replay of a frozen live trace. Not a scorer.

The live screen never flags the planted contradictions, so A2 cannot be
observed live. This rebuilds the measured passage evaluations, forces a
contradiction score on the known signal passages, and re-runs aggregation,
conflict resolution and the quality gate. Redundancy scores are kept exactly
as measured: a duplicate score must not remove the forced contradiction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, replace
from typing import Any

from app.services.research.assessment import AssessableEvidence
from app.services.research.evidence_screen import EvidenceJevScores
from app.services.research.quality import independence_key
from app.services.research.sufficiency_experiment.aggregate import aggregate_plan
from app.services.research.sufficiency_experiment.golden import GoldenCase
from app.services.research.sufficiency_experiment.jev_eval import (
    quality_input_from_evidence,
)
from app.services.research.sufficiency_experiment.obligations import (
    present_source_types,
)
from app.services.research.sufficiency_experiment.quality import quality_gate
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    GateInputs,
    NeedAggregation,
    PassageEvaluation,
)


def replay_case(
    case: GoldenCase,
    trace: dict[str, Any],
    *,
    contradiction_score: float = 0.95,
    config: ExperimentConfig | None = None,
    force: bool = True,
) -> dict[str, object]:
    settings = config or ExperimentConfig()
    signal_ids = {str(item["passage_id"]) for item in trace["signal_passages"]}
    rows = _evaluations(case, trace)
    forced = (
        force_contradictions(rows, sorted(signal_ids), score=contradiction_score)
        if force
        else rows
    )
    evidence_by_id = {item.evidence_id: item for item in case.evidence}
    present = {
        need.id: present_source_types(need, case.evidence) for need in case.plan.needs
    }
    aggregations = aggregate_plan(
        case.plan,
        forced,
        config=settings,
        evidence_by_id=evidence_by_id,
        source_types_by_id=present,
    )
    quality = quality_gate(aggregations, GateInputs(span_coverage=1.0), settings)
    conflicts = [conflict for row in aggregations for conflict in row.conflicts]
    return {
        "case_id": case.case_id,
        "forced_passage_ids": (
            [row.passage_id for row in forced if row.passage_id in signal_ids]
            if force
            else []
        ),
        "forced_contradiction_score": contradiction_score,
        "duplicate_scores": [
            row.scores.likely_duplicate_or_redundant
            for row in forced
            if row.passage_id in signal_ids
        ],
        "conflicts": [asdict(item) for item in conflicts],
        "unresolved_conflicts": [
            item for row in aggregations for item in row.unresolved_conflicts
        ],
        "gate_allows_sufficient": quality.allows_sufficient,
        "status": _status(aggregations, quality.allows_sufficient),
        "draft_result": _draft_result(aggregations, quality.allows_sufficient),
    }


def force_contradictions(
    rows: list[PassageEvaluation],
    passage_ids: list[str],
    *,
    score: float,
) -> list[PassageEvaluation]:
    forced = set(passage_ids)
    return [
        replace(row, scores=replace(row.scores, contradicts_current_evidence=score))
        if row.passage_id in forced
        else row
        for row in rows
    ]


def _evaluations(
    case: GoldenCase,
    trace: dict[str, Any],
) -> list[PassageEvaluation]:
    by_id: dict[str, AssessableEvidence] = {
        item.evidence_id: item for item in case.evidence
    }
    return [
        _evaluation(row, by_id[str(row["evidence_id"])])
        for row in trace["evaluations"]
    ]


def _evaluation(
    row: dict[str, Any],
    item: AssessableEvidence,
) -> PassageEvaluation:
    return PassageEvaluation(
        job_id=str(row["job_id"]),
        need_id=str(row["need_id"]),
        passage_id=str(row["passage_id"]),
        evidence_id=item.evidence_id,
        scores=EvidenceJevScores(
            evidence_id=item.evidence_id,
            source_type=item.source_type,
            content_hash=item.content_hash,
            relevant_to_question=float(row["relevant_to_question"]),
            directly_supports_answer=float(row["directly_supports_answer"]),
            contradicts_current_evidence=float(row["contradicts_current_evidence"]),
            material_new_information=float(row["material_new_information"]),
            likely_duplicate_or_redundant=float(row["likely_duplicate_or_redundant"]),
            primary_or_high_authority_for_question=float(
                row["primary_or_high_authority_for_question"]
            ),
            latency_ms=0.0,
        ),
        independence_key=independence_key(quality_input_from_evidence(item)),
    )


def _status(
    aggregations: Sequence[NeedAggregation],
    allows_sufficient: bool,
) -> str:
    if allows_sufficient and all(row.sufficient for row in aggregations):
        return "sufficient"
    if any(
        row.unknown_requirements or row.unresolved_conflicts for row in aggregations
    ):
        return "uncertain"
    return "insufficient"


def _draft_result(
    aggregations: Sequence[NeedAggregation],
    allows_sufficient: bool,
) -> str:
    return (
        "sufficient"
        if allows_sufficient and all(row.sufficient for row in aggregations)
        else "insufficient"
    )
