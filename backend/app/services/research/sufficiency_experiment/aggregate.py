"""Obligation aggregation. One supporting passage is never enough."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.sufficiency_experiment.obligations import obligations_for_need
from app.services.research.sufficiency_experiment.types import (
    EvidenceObligation,
    ExperimentConfig,
    ExperimentStatus,
    NeedAggregation,
    ObligationState,
    PassageEvaluation,
)


def aggregate_need(
    need: ResearchNeed,
    rows: Sequence[PassageEvaluation],
    *,
    config: ExperimentConfig,
    addressed_conflicts: Sequence[str] = (),
    source_types_present: Sequence[str] = (),
) -> NeedAggregation:
    declared = obligations_for_need(need)
    if not declared:
        return NeedAggregation(
            research_need_id=need.id,
            status="uncertain",
            sufficient=False,
            obligation_states=(),
            supporting_evidence_ids=(),
            contradictions=_contradictions(rows, config),
            unresolved_conflicts=(),
            missing_or_weak="Unknown evidence obligations; never sufficient.",
            unknown_requirements=True,
        )
    states = [
        _state(
            item,
            rows,
            config=config,
            addressed_conflicts=addressed_conflicts,
            source_types_present=source_types_present,
        )
        for item in declared
    ]
    contradictions = _contradictions(rows, config)
    unresolved = tuple(
        state.obligation_id
        for state in states
        if state.contradicting_passage_ids and not state.addressed
    )
    supporting = tuple(
        dict.fromkeys(
            row.evidence_id
            for row in rows
            if row.scores.directly_supports_answer >= config.support_threshold
        )
    )
    verified = all(state.verified for state in states)
    status = _status(verified, unresolved)
    return NeedAggregation(
        research_need_id=need.id,
        status=status,
        sufficient=status == "sufficient",
        obligation_states=tuple(states),
        supporting_evidence_ids=supporting,
        contradictions=contradictions,
        unresolved_conflicts=unresolved,
        missing_or_weak=_missing(states, unresolved),
        unknown_requirements=False,
    )


def aggregate_plan(
    plan: ResearchPlan,
    rows: Sequence[PassageEvaluation],
    *,
    config: ExperimentConfig,
    addressed_conflicts: Sequence[str] = (),
    source_types_by_id: dict[str, tuple[str, ...]] | None = None,
) -> list[NeedAggregation]:
    indexed: dict[str, list[PassageEvaluation]] = {need.id: [] for need in plan.needs}
    for row in rows:
        if row.need_id not in indexed:
            raise ValueError(f"evaluation cited unknown needs: {row.need_id}")
        indexed[row.need_id].append(row)
    missing = [need.id for need in plan.needs if not indexed[need.id]]
    if missing:
        raise ValueError(f"needs have no passage evaluations: {missing}")
    present = source_types_by_id or {}
    return [
        aggregate_need(
            need,
            indexed[need.id],
            config=config,
            addressed_conflicts=addressed_conflicts,
            source_types_present=present.get(need.id, ()),
        )
        for need in plan.needs
    ]


def _state(
    obligation: EvidenceObligation,
    rows: Sequence[PassageEvaluation],
    *,
    config: ExperimentConfig,
    addressed_conflicts: Sequence[str],
    source_types_present: Sequence[str],
) -> ObligationState:
    contradicting = _contradictions(rows, config)
    keys = {
        row.independence_key
        for row in rows
        if row.scores.relevant_to_question >= config.support_threshold
        and row.scores.directly_supports_answer >= config.support_threshold
    }
    if obligation.kind == "relevance":
        verified = any(
            row.scores.relevant_to_question >= config.support_threshold for row in rows
        )
    elif obligation.kind == "factual_support":
        verified = len(keys) >= obligation.min_independent_sources
        if contradicting and obligation.obligation_id not in addressed_conflicts:
            verified = False
    else:
        source = obligation.obligation_id.split("completeness:")[-1]
        verified = source in source_types_present
    return ObligationState(
        obligation_id=obligation.obligation_id,
        kind=obligation.kind,
        verified=verified,
        independent_support=len(keys),
        contradicting_passage_ids=contradicting,
        addressed=obligation.obligation_id in addressed_conflicts,
    )


def _contradictions(
    rows: Sequence[PassageEvaluation],
    config: ExperimentConfig,
) -> tuple[str, ...]:
    return tuple(
        row.passage_id
        for row in rows
        if row.scores.contradicts_current_evidence >= config.contradict_threshold
    )


def _status(verified: bool, unresolved: Sequence[str]) -> ExperimentStatus:
    if unresolved:
        return "uncertain"
    if verified:
        return "sufficient"
    return "insufficient"


def _missing(states: Sequence[ObligationState], unresolved: Sequence[str]) -> str:
    if unresolved:
        return "Material contradictions are preserved and not yet addressed."
    unmet = [state.obligation_id for state in states if not state.verified]
    if unmet:
        return "Mandatory obligations lack verified support: " + ", ".join(unmet)
    return ""
