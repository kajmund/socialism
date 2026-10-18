"""Rule B work on frozen C@8. Not a Coverage v3 run and does not claim 100 saved."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.evidence_curve import DEFAULT_V3
from overgraph_ingest.coverage.proof_contract import (
    COMPLETE_IN_UNIT,
    NEEDS_COMPLEMENTARY,
    UNRESOLVED_REFERENCE,
    run_proof_contract,
)

ROOT = Path(__file__).resolve().parents[2]
MEASURED_HOPS = {
    "Avtal_46_SaaS_avtal.docx": {
        "reason": "complete_proof",
        "relation": "PREVIOUS",
        "extra_text_units": 2,
        "would_classify": 1,
    },
    "Avtal_49_IT_drift_hostingavtal.docx": {
        "reason": "test_reference",
        "relation": "CLAUSE_4",
        "extra_text_units": 6,
        "would_classify": 6,
        "outcome": "dismiss_secrecy",
    },
}


def rule_b_work(contract: dict[str, object], *, coverage_v3: dict[str, object] | None = None) -> dict[str, object]:
    positives = list(contract.get("positives") or [])
    controls = list(contract.get("controls") or [])
    complete = [row for row in positives if row.get("proposed") == COMPLETE_IN_UNIT]
    complementary = [row for row in positives if row.get("proposed") == NEEDS_COMPLEMENTARY]
    unresolved = [
        row
        for row in positives + controls
        if row.get("proposed") == UNRESOLVED_REFERENCE
    ]
    false_complete = [row for row in controls if row.get("proposed") == COMPLETE_IN_UNIT]
    last_signal = max(
        (int(row.get("rank") or 0) for row in positives if row.get("rank") is not None),
        default=0,
    )
    gold_hops = [
        {**MEASURED_HOPS[path], "relative_path": path}
        for path in (row.get("relative_path") for row in complementary)
        if path in MEASURED_HOPS
    ]
    dismissive_hops = [
        {**MEASURED_HOPS[path], "relative_path": path}
        for path in (row.get("relative_path") for row in unresolved)
        if path in MEASURED_HOPS
    ]
    hop_classify_gold = sum(int(item["would_classify"]) for item in gold_hops)
    v3 = _carveout_v3(coverage_v3)
    return {
        "complete_from_first_candidate": len(complete),
        "positives_expected": len(positives),
        "necessary_hops": gold_hops,
        "necessary_hop_count": len(gold_hops),
        "dismissive_hops": dismissive_hops,
        "unresolved_references": [row.get("relative_path") for row in unresolved],
        "false_complete_controls": [row.get("relative_path") for row in false_complete],
        "false_complete_count": len(false_complete),
        "c8_classifications_to_last_gold_signal": last_signal,
        "would_classify_hops_to_complete_gold": hop_classify_gold,
        "rule_b_replay_classifications": last_signal + hop_classify_gold,
        "observed_v3_all_jev_yes_at": v3.get("first_all_jev_yes_at"),
        "observed_v3_complete_at": v3.get("first_complete_at"),
        "observed_v3_b5_classified": v3.get("classified"),
        "later_coverage_run_with_same_budget": "not_run",
        "does_not_claim_saved_classifications": True,
        "replay_of_c8_and_measured_hops": True,
    }


def run_proof_work(
    *,
    cache_root: Path | None = None,
    coverage_v3_path: Path | None = None,
) -> dict[str, object]:
    contract = run_proof_contract(cache_root=cache_root)
    coverage = None
    path = coverage_v3_path or DEFAULT_V3
    if path.is_file():
        coverage = json.loads(path.read_text(encoding="utf-8"))
    work = rule_b_work(contract, coverage_v3=coverage)
    return {
        "operation": "coverage",
        "experiment": "proof_work_v1",
        "coverage_v3_unchanged": True,
        "does_not_replace_c8": True,
        "no_new_controller": True,
        "proof_contract_applied_to_v3": False,
        "does_not_claim_saved_classifications": True,
        "evidence_layers": ("retrieval", "proof_evaluation", "navigation"),
        "reward_sufficient_evidence_not_more_steps": True,
        "gold_id": contract.get("gold_id"),
        "work": work,
    }


def _carveout_v3(coverage: dict[str, object] | None) -> dict[str, object]:
    if not coverage:
        return {}
    gold = next(
        (item for item in coverage.get("golds") or [] if item.get("gold_id") == "liability-secrecy-carveout"),
        {},
    )
    last = (list(gold.get("budgets") or []) or [{}])[-1]
    timeline = list(last.get("timeline") or [])
    first_yes = next(
        (point for point in timeline if int(point.get("documents_found") or 0) >= 7),
        None,
    )
    first_complete = next(
        (point for point in timeline if not point.get("unresolved_relevant")),
        None,
    )
    return {
        "first_all_jev_yes_at": None if first_yes is None else first_yes.get("classified"),
        "first_complete_at": None if first_complete is None else first_complete.get("classified"),
        "classified": last.get("classified"),
    }
