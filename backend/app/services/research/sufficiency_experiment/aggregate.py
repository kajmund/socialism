"""Deterministic per-need aggregation of Jev passage verdicts."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.types import (
    NeedAggregation,
    PassageEvaluation,
)


def aggregate_need(
    need_id: str,
    rows: Sequence[PassageEvaluation],
) -> NeedAggregation:
    supporting: list[str] = []
    contradictions: list[str] = []
    undecided: list[str] = []
    seen_support: set[str] = set()
    for row in rows:
        if row.need_id != need_id:
            continue
        if row.verdict == "SUPPORTED" and row.evidence_id not in seen_support:
            seen_support.add(row.evidence_id)
            supporting.append(row.evidence_id)
        elif row.verdict == "CONTRADICTS":
            contradictions.append(row.passage_id)
        elif row.verdict == "UNDECIDED":
            undecided.append(row.passage_id)
    if contradictions:
        return NeedAggregation(
            research_need_id=need_id,
            sufficient=False,
            supporting_evidence_ids=tuple(supporting),
            contradictions=tuple(contradictions),
            undecided_passage_ids=tuple(undecided),
            missing_or_weak="Jev found contradicting passages.",
            needs_narrative=False,
        )
    if supporting:
        return NeedAggregation(
            research_need_id=need_id,
            sufficient=True,
            supporting_evidence_ids=tuple(supporting),
            contradictions=(),
            undecided_passage_ids=tuple(undecided),
            missing_or_weak="",
            needs_narrative=False,
        )
    if undecided:
        return NeedAggregation(
            research_need_id=need_id,
            sufficient=False,
            supporting_evidence_ids=(),
            contradictions=(),
            undecided_passage_ids=tuple(undecided),
            missing_or_weak="Jev left passages undecided; no supporting passage.",
            needs_narrative=True,
        )
    return NeedAggregation(
        research_need_id=need_id,
        sufficient=False,
        supporting_evidence_ids=(),
        contradictions=(),
        undecided_passage_ids=(),
        missing_or_weak="No passage supported this ResearchNeed.",
        needs_narrative=False,
    )


def aggregate_plan(
    plan: ResearchPlan,
    rows: Sequence[PassageEvaluation],
) -> list[NeedAggregation]:
    indexed = {need.id: [] for need in plan.needs}
    for row in rows:
        if row.need_id in indexed:
            indexed[row.need_id].append(row)
    missing = [row.need_id for row in rows if row.need_id not in indexed]
    if missing:
        raise ValueError(f"evaluation cited unknown needs: {missing}")
    unevaluated = [need.id for need in plan.needs if not indexed[need.id]]
    if unevaluated:
        raise ValueError(f"needs have no passage evaluations: {unevaluated}")
    return [aggregate_need(need.id, indexed[need.id]) for need in plan.needs]
