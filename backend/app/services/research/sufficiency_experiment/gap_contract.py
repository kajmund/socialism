"""B1 falsifiable gap contract and a deterministic gap baseline.

The narrative model may only hypothesise gaps; a deterministic validator checks
need ids, allowlisted workflows and machine-checkable anchors. Verified gaps
are the only ones that may ever reach B2 execution. NO_GAP_FOUND never proves
completeness.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.tools import ALLOWED_WORKFLOWS
from app.services.research.sufficiency_experiment.types import (
    CoverageReport,
    GapHypothesis,
    GapVerdict,
    NeedAggregation,
    NarrativeGapReport,
    PairSelection,
)

B1_GAP_SYSTEM_PROMPT = (
    "You are a falsifiable evidence-gap reviewer for an evidence-sufficiency "
    "workflow. Choose exactly one verdict: VERIFIED_GAP when a concrete gap is "
    "supported by supplied metadata or evidence anchors; SUSPECTED_GAP when you "
    "have a specific testable suspicion that evidence is missing; NO_GAP_FOUND "
    "when you find no concrete gap; UNDETERMINED when the supplied material "
    "cannot decide. Never report a gap only because additional evidence could "
    "theoretically exist. NO_GAP_FOUND does not prove completeness. For every "
    "gap report need_id, what is missing, the observations that motivate it, a "
    "suggested workflow from the allowlist, and anchors in the form claim:<id>, "
    "pair:<pair_id> or coverage:<reason>. A VERIFIED_GAP needs at least one "
    "valid anchor. Do not decide sufficiency and do not claim that unreviewed "
    "material was reviewed."
)


@dataclass(frozen=True)
class GapValidation:
    verdict: GapVerdict
    errors: tuple[str, ...]
    verified_gap_ids: tuple[str, ...]


def validate_gap_report(
    report: NarrativeGapReport,
    *,
    need_ids: Sequence[str],
    claim_ids: Sequence[str],
    pair_ids: Sequence[str],
    coverage_reasons: Sequence[str],
    aggregation_ids: Sequence[str] = (),
) -> GapValidation:
    known_need = set(need_ids)
    known_claim = set(claim_ids)
    known_pair = set(pair_ids)
    known_reason = set(coverage_reasons)
    known_aggregation = set(aggregation_ids)
    errors: list[str] = []
    verified: list[str] = []
    for gap in report.gaps:
        if gap.need_id not in known_need:
            errors.append(f"unknown need: {gap.need_id}")
        if gap.suggested_workflow not in ALLOWED_WORKFLOWS:
            errors.append(f"workflow not allowed: {gap.suggested_workflow}")
        if not gap.missing.strip():
            errors.append(f"empty missing text: {gap.gap_id}")
        anchors_ok = _anchors_valid(
            gap.anchors,
            claim_ids=known_claim,
            pair_ids=known_pair,
            coverage_reasons=known_reason,
            aggregation_ids=known_aggregation,
        )
        if not anchors_ok:
            errors.append(f"invalid anchor on {gap.gap_id}")
        if report.verdict == "VERIFIED_GAP" and not anchors_ok:
            errors.append(f"VERIFIED_GAP without valid anchor: {gap.gap_id}")
        if report.verdict == "VERIFIED_GAP":
            verified.append(gap.gap_id)
    if report.verdict == "NO_GAP_FOUND" and report.gaps:
        errors.append("NO_GAP_FOUND with reported gaps")
    if report.verdict == "VERIFIED_GAP" and not report.gaps:
        errors.append("VERIFIED_GAP without gaps")
    verdict: GapVerdict = "UNDETERMINED" if errors else (report.verdict or "UNDETERMINED")
    return GapValidation(
        verdict=verdict,
        errors=tuple(errors),
        verified_gap_ids=tuple(verified) if not errors else (),
    )


def deterministic_gap_hypotheses(
    plan: ResearchPlan,
    aggregations: Sequence[NeedAggregation],
    coverage: CoverageReport | None,
    selection: PairSelection | None,
) -> tuple[GapHypothesis, ...]:
    gaps: list[GapHypothesis] = []
    if coverage is not None:
        for level in coverage.levels:
            if level.level != "conflict_candidate":
                continue
            if "pair_budget_omitted" in level.reasons:
                for need in plan.needs:
                    gaps.append(
                        GapHypothesis(
                            gap_id=f"deterministic:{need.id}:uncompared_pairs",
                            need_id=need.id,
                            missing="candidate fact pairs were omitted by the pair budget",
                            observations=tuple(level.reasons),
                            suggested_workflow="evaluate_passages",
                            anchors=("coverage:pair_budget_omitted",),
                        )
                    )
    if selection is not None and selection.omitted_by_budget == 0:
        pass
    for row in aggregations:
        if row.sufficient or row.unresolved_conflicts or not row.missing_or_weak:
            continue
        gaps.append(
            GapHypothesis(
                gap_id=f"deterministic:{row.research_need_id}:obligations",
                need_id=row.research_need_id,
                missing=row.missing_or_weak,
                observations=("aggregation_not_sufficient",),
                suggested_workflow="evaluate_passages",
                anchors=(f"aggregation:{row.research_need_id}",),
            )
        )
    return tuple(gaps)


def deterministic_verdict(gaps: Sequence[GapHypothesis]) -> GapVerdict:
    return "VERIFIED_GAP" if gaps else "NO_GAP_FOUND"


def _coverage_reason(coverage: CoverageReport | None) -> str:
    if coverage is None:
        return "not_measured"
    reasons = [reason for level in coverage.levels for reason in level.reasons]
    return reasons[0] if reasons else "none"


def _anchors_valid(
    anchors: Sequence[str],
    *,
    claim_ids: set[str],
    pair_ids: set[str],
    coverage_reasons: set[str],
    aggregation_ids: set[str],
) -> bool:
    if not anchors:
        return False
    for anchor in anchors:
        kind, _, value = anchor.partition(":")
        if kind == "claim" and value in claim_ids:
            continue
        if kind == "pair" and value in pair_ids:
            continue
        if kind == "coverage" and value in coverage_reasons:
            continue
        if kind == "aggregation" and value in aggregation_ids:
            continue
        return False
    return True
