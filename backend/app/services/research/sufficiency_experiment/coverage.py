"""Five coverage levels for the experiment. Never one combined percentage.

Each level has an explicit control. Process levels gate `sufficient`; the
conflict-candidate level additionally needs the pair facit when one is bound.
A pair that was never generated is invisible to a job counter, so process
completeness alone is not reported as measured completeness.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.assessment import AssessableEvidence
from app.services.research.sufficiency_experiment.types import (
    ClaimCoverage,
    CoverageLevel,
    CoverageReport,
    PairEvaluation,
    PairFacit,
    PairSelection,
)

LEVELS = (
    "ingestion",
    "passage",
    "claim",
    "conflict_candidate",
    "narrative",
)


def build_coverage_report(
    *,
    evidence: Sequence[AssessableEvidence],
    source_chars: int,
    judged_chars: int,
    claim_coverage: ClaimCoverage | None,
    pair_selection: PairSelection | None,
    pair_evaluations: Sequence[PairEvaluation],
    pair_facit: PairFacit | None = None,
) -> CoverageReport:
    return CoverageReport(
        levels=(
            _ingestion(evidence),
            _passage(source_chars, judged_chars),
            _claim(claim_coverage),
            _conflict(pair_selection, pair_evaluations, pair_facit),
            _narrative(),
        )
    )


def _ingestion(evidence: Sequence[AssessableEvidence]) -> CoverageLevel:
    found_with = sum(
        1
        for item in evidence
        if item.status == "found" and bool((item.excerpt or "").strip())
    )
    found_without = sum(
        1
        for item in evidence
        if item.status == "found" and not (item.excerpt or "").strip()
    )
    not_found = len(evidence) - found_with - found_without
    status = "complete" if found_without == 0 else "incomplete"
    return CoverageLevel(
        level="ingestion",
        status=status,
        control="provided_evidenceset",
        counts=(
            ("provided", len(evidence)),
            ("found_with_excerpt", found_with),
            ("found_without_excerpt", found_without),
            ("not_found", not_found),
        ),
        reasons=("found_without_excerpt",) if found_without else (),
        note="Upstream ingestion is outside the provided EvidenceSet.",
        gate_complete=status == "complete",
    )


def _passage(source_chars: int, judged_chars: int) -> CoverageLevel:
    ratio = 1.0 if source_chars == 0 else judged_chars / source_chars
    complete = ratio >= 1.0
    return CoverageLevel(
        level="passage",
        status="complete" if complete else "incomplete",
        control="character_cover",
        counts=(
            ("source_chars", source_chars),
            ("judged_chars", judged_chars),
        ),
        reasons=() if complete else ("judged_chars_below_source",),
        gate_complete=complete,
    )


def _claim(claim_coverage: ClaimCoverage | None) -> CoverageLevel:
    if claim_coverage is None:
        return CoverageLevel(
            level="claim",
            status="not_measured",
            control="candidate_status",
            note="No claim extraction ran on the programmatic path.",
        )
    complete = claim_coverage.complete
    return CoverageLevel(
        level="claim",
        status="complete" if complete else "incomplete",
        control="candidate_status",
        counts=(
            ("candidates", claim_coverage.candidates),
            ("extracted", claim_coverage.extracted),
            ("uncertain", claim_coverage.uncertain),
            ("unprocessed", claim_coverage.unprocessed),
        ),
        reasons=claim_coverage.reasons if not complete else (),
        gate_complete=complete,
    )


def _conflict(
    pair_selection: PairSelection | None,
    pair_evaluations: Sequence[PairEvaluation],
    pair_facit: PairFacit | None,
) -> CoverageLevel:
    selected = {pair.pair_id for pair in pair_selection.selected} if pair_selection else set()
    judged = {
        row.pair_id for row in pair_evaluations if row.status != "unevaluated"
    }
    uncertain = sum(1 for row in pair_evaluations if row.status == "uncertain")
    unevaluated = sum(
        1 for row in pair_evaluations if row.status == "unevaluated"
    )
    omitted = pair_selection.omitted_by_budget if pair_selection else 0
    process_complete = omitted == 0 and unevaluated == 0
    expected = set(pair_facit.candidate_pairs if pair_facit else ()) | set(
        pair_facit.contradiction_pairs if pair_facit else ()
    )
    missing = expected - judged
    counts = (
        ("selected", len(selected)),
        ("judged", len(judged)),
        ("uncertain", uncertain),
        ("unevaluated", unevaluated),
        ("omitted_by_budget", omitted),
        ("facit_expected", len(expected)),
        ("facit_missing", len(missing)),
    )
    candidates_exist = bool(pair_selection and pair_selection.candidates)
    if not selected and not expected and not candidates_exist:
        return CoverageLevel(
            level="conflict_candidate",
            status="not_applicable",
            control="process",
            counts=counts,
            note="No claim pair exists for this EvidenceSet.",
        )
    if pair_facit is None:
        reasons: list[str] = []
        if omitted:
            reasons.append("pair_budget_omitted")
        if unevaluated:
            reasons.append("pair_unevaluated")
        return CoverageLevel(
            level="conflict_candidate",
            status="not_measured" if process_complete else "incomplete",
            control="process",
            counts=counts,
            reasons=tuple(reasons),
            note="No pair facit bound; process completeness only.",
            gate_complete=process_complete,
        )
    complete = process_complete and not missing
    reasons = []
    if omitted:
        reasons.append("pair_budget_omitted")
    if unevaluated:
        reasons.append("pair_unevaluated")
    if missing:
        reasons.append("facit_pair_missing")
    return CoverageLevel(
        level="conflict_candidate",
        status="complete" if complete else "incomplete",
        control="process_and_facit",
        counts=counts,
        reasons=tuple(reasons),
        gate_complete=complete,
    )


def _narrative() -> CoverageLevel:
    return CoverageLevel(
        level="narrative",
        status="not_applicable",
        control="none",
        note="Variant B is not implemented; no narrative review ran.",
        gate_complete=True,
    )
