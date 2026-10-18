"""Accepted findings from the read-only review. Does not change v3 or start A/B."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_diagnosis import QUALITY_REFERENCE

ROOT = Path(__file__).resolve().parents[2]
STATIC_REVIEW_BASELINE_ID = "phase2-static-review-v1"
STATIC_REVIEW_BASELINE_PATH = ROOT / "baselines" / f"{STATIC_REVIEW_BASELINE_ID}.json"

ACCEPTED = {
    "v3_composite_yes_plus_hop_is_not_verified_relation": True,
    "admit_evidence_found_not_called_by_resolve_status": True,
    "required_parts_are_text_presence_not_relation": True,
    "evidence_run_can_substitute_gold_snippet": True,
    "lexical_rules_are_formulation_bound": True,
    "clause_and_anaphor_are_known_formulations": True,
    "zero_false_approvals_is_frozen_set_not_population": True,
    "nineteen_of_fifty_three_is_not_v3_verification": True,
    "traces_only_for_evidence_found": True,
    "joined_link_re_in_traces_is_diagnostic": True,
    "exhaustive_hybrid_score_is_not_rrf": True,
    "c8_cache_can_fall_back_to_first_run": True,
    "budget_and_controller_are_separate_policies": True,
    "do_not_overwrite_is_writer_guard_not_immutability": True,
}

CONSTRAINTS = {
    "does_not_change_v3": True,
    "does_not_start_next_ability": True,
    "does_not_treat_19_53_as_general_legal_understanding": True,
    "next_ability_still_needs_independent_formulations": True,
}


def review_payload() -> dict[str, object]:
    return {
        "operation": "review",
        "experiment": "static_review_v1",
        "source": "read_only_code_review",
        "no_new_jev": True,
        "applied_to_v3": False,
        "quality_reference": QUALITY_REFERENCE,
        "accepted": ACCEPTED,
        **CONSTRAINTS,
    }


def freeze_static_review_baseline(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or review_payload()
    return {
        "id": STATIC_REVIEW_BASELINE_ID,
        "label": (
            "Frozen: accepted findings from the read-only review of "
            "experiments/overgraph_ingest. Does not change v3. Does not start "
            "the next ability. 19/53 is an experimental curve, not v3 verification."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "does_not_start_next_ability": True,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "accepted": body.get("accepted"),
            "does_not_change_v3": True,
            "does_not_start_next_ability": True,
        },
    }


def write_static_review_baseline(path: Path | None = None) -> Path:
    target = path or STATIC_REVIEW_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_static_review_baseline(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
