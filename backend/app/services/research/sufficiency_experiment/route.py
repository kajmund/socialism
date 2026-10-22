"""Jev route using existing assessment NOUL + classify_research_decision."""

from __future__ import annotations

from collections.abc import Sequence

from app.jev.system import JevSystemOne, noul_confidence, parse_noul
from app.services.research.fast_controller import (
    ASSESSMENT_QUESTIONS,
    classify_research_decision,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    NeedAggregation,
    PassageEvaluation,
    QualityDecision,
    RouteChoice,
    RouteDecision,
)

ROUTE_CRITERIA = (
    "FINISH: no remaining applicable subworkflow; emit current status",
    "RUN_SUBWORKFLOW: a typed workflow can address conflicts or missing evals",
    "ESCALATE_NARRATIVE: quality gate permits narrative and no subworkflow applies",
    "UNCERTAIN: requirements, conflicts, or budgets remain unresolved",
)


def map_jev_outcome(
    outcome: str,
    quality: QualityDecision,
    aggregations: Sequence[NeedAggregation],
) -> RouteChoice:
    if quality.applicable_subworkflows:
        return "RUN_SUBWORKFLOW"
    if outcome == "sufficient" and quality.allows_sufficient:
        return "FINISH"
    if outcome == "insufficient" and not quality.applicable_subworkflows:
        return "FINISH"
    if quality.escalate_permitted:
        return "ESCALATE_NARRATIVE"
    return "UNCERTAIN"


def validate_route(
    choice: RouteChoice,
    quality: QualityDecision,
    *,
    evidence_ids: Sequence[str],
    jev_outcome: str | None,
    jev_answers: Sequence[tuple[str, float]] = (),
) -> RouteDecision:
    rejection = None
    if choice == "FINISH" and quality.allows_sufficient is False and jev_outcome == "sufficient":
        rejection = "FINISH_sufficient rejected: obligations or coverage incomplete"
    if choice == "ESCALATE_NARRATIVE" and quality.applicable_subworkflows:
        rejection = "subworkflow still applies; narrative is not allowed"
    if choice == "ESCALATE_NARRATIVE" and not quality.escalate_permitted:
        rejection = "quality gate forbids narrative"
    if choice == "RUN_SUBWORKFLOW" and not quality.applicable_subworkflows:
        rejection = "no applicable subworkflow"
    if choice == "FINISH" and quality.budget_exhausted:
        rejection = "budget exhausted cannot finish as sufficient"
        if quality.allows_sufficient:
            rejection = "budget exhausted"
    valid = rejection is None
    final: RouteChoice = choice if valid else "UNCERTAIN"
    if not valid and choice == "FINISH" and jev_outcome == "sufficient":
        final = "UNCERTAIN"
    sub = quality.applicable_subworkflows[0] if final == "RUN_SUBWORKFLOW" else None
    cited = tuple(evidence_ids)
    return RouteDecision(
        choice=final,
        rationale="; ".join(quality.reasons) or "validated Jev route",
        evidence_ids=cited,
        criteria=ROUTE_CRITERIA,
        subworkflow=sub,
        valid=valid,
        jev_outcome=jev_outcome,
        rejection=rejection,
        jev_answers=tuple(jev_answers),
    )


async def decide_route(
    client: JevSystemOne,
    config: ExperimentConfig,
    aggregations: Sequence[NeedAggregation],
    quality: QualityDecision,
    *,
    state: dict[str, object],
) -> RouteDecision:
    result = await client.ask(
        state=state,
        questions=ASSESSMENT_QUESTIONS,
        model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
    )
    answerable = parse_noul(result.answers, "answerable_now")
    gap = parse_noul(result.answers, "material_gap")
    contradiction = parse_noul(result.answers, "contradiction")
    follow_up = parse_noul(result.answers, "follow_up_change")
    additional = parse_noul(result.answers, "additional_source")
    confidence = min(
        noul_confidence(value)
        for value in (answerable, gap, contradiction, follow_up, additional)
    )
    outcome = classify_research_decision(
        answerable_now=answerable,
        material_gap=gap,
        contradiction=contradiction,
        follow_up_change=follow_up,
        additional_source=additional,
        confidence=confidence,
        sufficient_threshold=0.9,
        incomplete_threshold=0.85,
        confidence_threshold=0.8,
    )
    proposed = map_jev_outcome(outcome, quality, aggregations)
    cited = [item for row in aggregations for item in row.supporting_evidence_ids]
    cited.extend(item for row in aggregations for item in row.contradictions)
    answers = (
        ("answerable_now", answerable),
        ("material_gap", gap),
        ("contradiction", contradiction),
        ("follow_up_change", follow_up),
        ("additional_source", additional),
        ("confidence", confidence),
    )
    return validate_route(
        proposed,
        quality,
        evidence_ids=cited,
        jev_outcome=outcome,
        jev_answers=answers,
    )


def route_state(
    aggregations: Sequence[NeedAggregation],
    quality: QualityDecision,
) -> dict[str, object]:
    """Passage-level summary for ASSESSMENT_QUESTIONS. Not compact_research_state."""
    return {
        "needs": [
            {
                "research_need_id": row.research_need_id,
                "status": row.status,
                "sufficient": row.sufficient,
                "unknown_requirements": row.unknown_requirements,
                "unresolved_conflicts": list(row.unresolved_conflicts),
                "verified_obligations": [
                    state.obligation_id for state in row.obligation_states if state.verified
                ],
                "unverified_obligations": [
                    state.obligation_id
                    for state in row.obligation_states
                    if not state.verified
                ],
            }
            for row in aggregations
        ],
        "unknown_requirements": any(row.unknown_requirements for row in aggregations),
        "unresolved_conflicts": [
            item for row in aggregations for item in row.unresolved_conflicts
        ],
        "obligations_verified": bool(aggregations)
        and all(row.sufficient for row in aggregations),
        "span_coverage": quality.span_coverage,
        "semantic_complete": quality.semantic_complete,
        "reasons": list(quality.reasons),
    }


def resolve_conflict(
    aggregations: Sequence[NeedAggregation],
    evaluations: Sequence[PassageEvaluation],
    *,
    config: ExperimentConfig,
) -> tuple[str, ...]:
    """Address a conflict only when every contradicting passage is a duplicate.

    Does not drop evidence and does not majority-vote remaining contradictions.
    """
    duplicates = {
        row.passage_id
        for row in evaluations
        if row.scores.likely_duplicate_or_redundant >= config.support_threshold
    }
    addressed: list[str] = []
    for row in aggregations:
        for obligation in row.unresolved_conflicts:
            contradicting = next(
                (
                    state.contradicting_passage_ids
                    for state in row.obligation_states
                    if state.obligation_id == obligation
                ),
                (),
            )
            if contradicting and all(item in duplicates for item in contradicting):
                addressed.append(obligation)
    return tuple(addressed)
