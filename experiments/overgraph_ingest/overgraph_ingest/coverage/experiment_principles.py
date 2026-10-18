"""Bench rules after the static review. Does not change v3 or start a new ability."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_diagnosis import QUALITY_REFERENCE

ROOT = Path(__file__).resolve().parents[2]
PRINCIPLES_BASELINE_ID = "phase2-experiment-principles-v1"
PRINCIPLES_BASELINE_PATH = ROOT / "baselines" / f"{PRINCIPLES_BASELINE_ID}.json"

PARTS = {
    "coverage_v3": "frozen_yes_plus_hop",
    "experimental_evidence_chain": "19/53_on_frozen_material",
    "future_proof_evaluation": "not_decided",
}

REQUIREMENTS = {
    "measurement_integrity": (
        "Quality metrics must say whether evidence came from retrieval "
        "or was supplied from gold. Official comparisons require a named "
        "C@8 baseline, not the first run in a cache file."
    ),
    "independent_generalization": (
        "New legal formulations are tested without first adapting the rules "
        "to those formulations."
    ),
    "later_architectural_consolidation": (
        "Experimental proof rules are not production architecture. "
        "Do not stack them into the default controller."
    ),
}

KNOWN_ISSUES_LEFT_IN_PLACE = (
    "evidence_run_gold_snippet_fallback",
    "c8_cache_first_run_fallback",
    "v3_composite_yes_plus_hop",
)

EXPERIMENTAL_RULES_NOT_PRODUCTION = (
    "proof_link",
    "proof_relation",
    "chain_contract",
    "clause_resolve",
    "anaphor_resolve",
    "proof_gate",
    "proof_predicate",
)


def principles_payload() -> dict[str, object]:
    return {
        "operation": "principles",
        "experiment": "experiment_principles_v1",
        "applied_to_v3": False,
        "does_not_start_next_ability": True,
        "does_not_change_existing_helpers": True,
        "quality_reference": QUALITY_REFERENCE,
        "parts": PARTS,
        "requirements": REQUIREMENTS,
        "known_issues_left_in_place": KNOWN_ISSUES_LEFT_IN_PLACE,
        "experimental_rules_are_not_production": EXPERIMENTAL_RULES_NOT_PRODUCTION,
        "search_is_closer_to_done_than_legal_verification": True,
        "nineteen_of_fifty_three_is_not_v3": True,
    }


def freeze_principles_baseline(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or principles_payload()
    return {
        "id": PRINCIPLES_BASELINE_ID,
        "label": (
            "Frozen: three bench requirements after the static review. "
            "Measurement integrity, independent generalization, later "
            "consolidation. Does not change v3. Does not start the next ability."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "does_not_start_next_ability": True,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "parts": body.get("parts"),
            "requirements": body.get("requirements"),
            "known_issues_left_in_place": body.get("known_issues_left_in_place"),
            "experimental_rules_are_not_production": body.get(
                "experimental_rules_are_not_production"
            ),
            "search_is_closer_to_done_than_legal_verification": True,
        },
    }


def write_principles_baseline(path: Path | None = None) -> Path:
    target = path or PRINCIPLES_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_principles_baseline(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
