"""B1: falsifiable gap hypotheses are validated deterministically."""

from __future__ import annotations

from app.services.research.sufficiency_experiment.gap_contract import (
    deterministic_gap_hypotheses,
    deterministic_verdict,
    validate_gap_report,
)
from app.services.research.sufficiency_experiment.golden import late_evidence
from app.services.research.sufficiency_experiment.types import (
    CoverageLevel,
    CoverageReport,
    GapHypothesis,
    NarrativeGapReport,
    NeedAggregation,
)


def _report(verdict: str, gaps=()) -> NarrativeGapReport:
    return NarrativeGapReport(
        needs_more_evidence=verdict in {"VERIFIED_GAP", "SUSPECTED_GAP"},
        missing_evidence=(),
        questions=(),
        suggested_workflows=(),
        cited_claim_ids=(),
        rationale="test",
        verdict=verdict,  # type: ignore[arg-type]
        gaps=gaps,
    )


def _gap(*, anchors=("claim:c1",), workflow="evaluate_passages") -> GapHypothesis:
    return GapHypothesis(
        gap_id="g1",
        need_id="research_1",
        missing="the contra passage is not compared",
        observations=("one support claim has no compared counterpart",),
        suggested_workflow=workflow,
        anchors=anchors,
    )


def test_verified_gap_requires_machine_checkable_anchor() -> None:
    validation = validate_gap_report(
        _report("VERIFIED_GAP", (_gap(),)),
        need_ids=("research_1",),
        claim_ids=("c1",),
        pair_ids=(),
        coverage_reasons=(),
    )
    assert validation.verdict == "VERIFIED_GAP"
    assert validation.verified_gap_ids == ("g1",)
    assert validation.errors == ()


def test_invalid_anchor_downgrades_to_undetermined() -> None:
    validation = validate_gap_report(
        _report("VERIFIED_GAP", (_gap(anchors=("claim:missing",)),)),
        need_ids=("research_1",),
        claim_ids=("c1",),
        pair_ids=(),
        coverage_reasons=(),
    )
    assert validation.verdict == "UNDETERMINED"
    assert validation.verified_gap_ids == ()


def test_unknown_workflow_and_empty_missing_are_rejected() -> None:
    validation = validate_gap_report(
        _report("SUSPECTED_GAP", (_gap(workflow="search"),)),
        need_ids=("research_1",),
        claim_ids=("c1",),
        pair_ids=(),
        coverage_reasons=(),
    )
    assert validation.verdict == "UNDETERMINED"


def test_no_gap_found_with_gaps_is_invalid() -> None:
    validation = validate_gap_report(
        _report("NO_GAP_FOUND", (_gap(),)),
        need_ids=("research_1",),
        claim_ids=("c1",),
        pair_ids=(),
        coverage_reasons=(),
    )
    assert validation.verdict == "UNDETERMINED"


def test_verified_gap_without_gaps_is_invalid() -> None:
    validation = validate_gap_report(
        _report("VERIFIED_GAP"),
        need_ids=("research_1",),
        claim_ids=("c1",),
        pair_ids=(),
        coverage_reasons=(),
    )
    assert validation.verdict == "UNDETERMINED"


def test_deterministic_detector_uses_budget_and_obligations() -> None:
    case = late_evidence()
    coverage = CoverageReport(
        (
            CoverageLevel(
                level="conflict_candidate",
                status="incomplete",  # type: ignore[arg-type]
                control="pair_budget",  # type: ignore[arg-type]
                reasons=("pair_budget_omitted",),
                gate_complete=False,
            ),
        )
    )
    aggregations = (
        NeedAggregation(
            research_need_id="research_1",
            status="insufficient",
            sufficient=False,
            obligation_states=(),
            supporting_evidence_ids=(),
            contradictions=(),
            unresolved_conflicts=(),
            missing_or_weak="required source type is missing",
            unknown_requirements=False,
        ),
    )
    gaps = deterministic_gap_hypotheses(
        case.plan, aggregations, coverage, None
    )
    assert len(gaps) == 2
    assert deterministic_verdict(gaps) == "VERIFIED_GAP"
    validation = validate_gap_report(
        _report("VERIFIED_GAP", gaps),
        need_ids=("research_1",),
        claim_ids=(),
        pair_ids=(),
        coverage_reasons=("pair_budget_omitted",),
        aggregation_ids=("research_1",),
    )
    assert validation.verdict == "VERIFIED_GAP"


def test_deterministic_detector_does_not_call_unresolved_conflict_a_gap() -> None:
    case = late_evidence()
    aggregations = (
        NeedAggregation(
            research_need_id="research_1",
            status="insufficient",
            sufficient=False,
            obligation_states=(),
            supporting_evidence_ids=(),
            contradictions=("c1",),
            unresolved_conflicts=("c1",),
            missing_or_weak="unresolved conflict",
            unknown_requirements=False,
        ),
    )
    assert deterministic_gap_hypotheses(case.plan, aggregations, None, None) == ()


def test_real_anchor_for_wrong_need_is_rejected() -> None:
    validation = validate_gap_report(
        _report("VERIFIED_GAP", (_gap(),)),
        need_ids=("research_1", "research_2"),
        claim_ids=("c1",),
        pair_ids=(),
        coverage_reasons=(),
        available_anchors={"claim:c1": "research_2"},
    )
    assert validation.verdict == "UNDETERMINED"


def test_constructed_anchor_not_offered_is_rejected() -> None:
    validation = validate_gap_report(
        _report("VERIFIED_GAP", (_gap(anchors=("claim:c2",)),)),
        need_ids=("research_1",),
        claim_ids=("c1", "c2"),
        pair_ids=(),
        coverage_reasons=(),
        available_anchors={"claim:c1": "research_1"},
    )
    assert validation.verdict == "UNDETERMINED"
