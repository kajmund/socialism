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
    ExperimentStatus,
    NeedAggregation,
    QualityDecision,
    RouteChoice,
    RouteDecision,
)

SUFFICIENT_THRESHOLD = 0.9
INCOMPLETE_THRESHOLD = 0.85
CONFIDENCE_THRESHOLD = 0.8

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


def authoritative_outcome(
    *,
    answerable_now: float,
    material_gap: float,
    contradiction: float,
    confidence: float,
) -> str:
    """Four-signal authority. follow_up/additional never veto sufficient."""
    risk_ceiling = 1.0 - SUFFICIENT_THRESHOLD
    if (
        confidence >= CONFIDENCE_THRESHOLD
        and answerable_now >= SUFFICIENT_THRESHOLD
        and material_gap <= risk_ceiling
        and contradiction <= risk_ceiling
    ):
        return "sufficient"
    if confidence >= CONFIDENCE_THRESHOLD and (
        material_gap >= INCOMPLETE_THRESHOLD
        or answerable_now <= (1.0 - INCOMPLETE_THRESHOLD)
    ):
        return "insufficient"
    return "uncertain"


def map_route_outcome(
    final_outcome: str,
    quality: QualityDecision,
) -> RouteChoice:
    if quality.applicable_subworkflows:
        return "RUN_SUBWORKFLOW"
    if quality.allows_sufficient:
        return "FINISH"
    if quality.escalate_permitted:
        return "ESCALATE_NARRATIVE"
    return "FINISH"


def validate_route(
    choice: RouteChoice,
    quality: QualityDecision,
    *,
    evidence_ids: Sequence[str],
    jev_outcome: str | None,
    jev_answers: Sequence[tuple[str, float]] = (),
    final_outcome: str | None = None,
) -> RouteDecision:
    rejection = None
    if choice == "FINISH" and final_outcome is None:
        rejection = "FINISH without final outcome"
    if (
        choice == "FINISH"
        and final_outcome == "sufficient"
        and quality.allows_sufficient is False
    ):
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
        final_outcome=final_outcome,  # type: ignore[arg-type]
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
        sufficient_threshold=SUFFICIENT_THRESHOLD,
        incomplete_threshold=INCOMPLETE_THRESHOLD,
        confidence_threshold=CONFIDENCE_THRESHOLD,
    )
    final_outcome = authoritative_outcome(
        answerable_now=answerable,
        material_gap=gap,
        contradiction=contradiction,
        confidence=confidence,
    )
    proposed = map_route_outcome(final_outcome, quality)
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
        final_outcome=final_outcome,
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



def status_from_route(
    route: RouteDecision | None,
    quality: QualityDecision | None,
    aggregations: Sequence[NeedAggregation],
) -> tuple[ExperimentStatus, str | None]:
    """Final status from an explicit route outcome. No implicit consent."""
    if route is None:
        return "failed", "route_missing"
    if route.choice == "FINISH":
        return _finish_status(route, quality, aggregations)
    if route.choice == "UNCERTAIN":
        return (
            ("insufficient", route.rejection)
            if route.rejection
            else ("uncertain", None)
        )
    return "uncertain", None


def _finish_status(
    route: RouteDecision,
    quality: QualityDecision | None,
    aggregations: Sequence[NeedAggregation],
) -> tuple[ExperimentStatus, str | None]:
    if route.final_outcome is None:
        return "failed", "route_invalid"
    if route.final_outcome == "sufficient":
        allowed = bool(
            route.valid
            and quality is not None
            and quality.allows_sufficient
            and all(row.sufficient for row in aggregations)
        )
        return (
            ("sufficient", None)
            if allowed
            else ("insufficient", "route_sufficient_rejected")
        )
    if route.final_outcome == "insufficient":
        return "insufficient", None
    return "uncertain", None
