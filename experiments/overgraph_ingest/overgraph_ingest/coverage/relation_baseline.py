"""Freeze Coverage v3 + Rule B on the carve-out. Does not replace v3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from overgraph_ingest.coverage.compare import gold_row

RELATION_BASELINE_ID = "phase2-coverage-v3-relation-carveout"
RELATION_BASELINE_LABEL = (
    "Experimental: Coverage v3 with Rule B (relation-in-text) on "
    "liability-secrecy-carveout. Not ready for the default controller."
)
RELATION_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{RELATION_BASELINE_ID}.json"
)
FALSE_COMPLETE_REASON = "joined_units_treat_secrecy_heading_as_carveout"


def freeze_relation_carveout_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    versus = payload.get("versus_baseline_v3") or {}
    evidence = versus.get("first_complete_evidence") or {}
    treatment_first = evidence.get("treatment") or {}
    baseline_first = evidence.get("baseline") or {}
    gold = gold_row(payload, "liability-secrecy-carveout")
    budgets = {
        int(row["budget"]): row for row in gold.get("budgets") or [] if row.get("budget") is not None
    }
    b1 = budgets.get(1) or {}
    b2 = budgets.get(2) or {}
    b3 = budgets.get(3) or {}
    b5 = budgets.get(5) or {}
    false_complete = list(b5.get("evidence_found_nonrelevant") or [])
    return {
        "id": RELATION_BASELINE_ID,
        "label": RELATION_BASELINE_LABEL,
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "ready_for_default_controller": False,
        "replay_14_is_not_the_live_result": True,
        "controller": "deterministic_v3",
        "proof_rule": "relation",
        "classify_unchanged": True,
        "default_retriever_unchanged": True,
        "gold_id": "liability-secrecy-carveout",
        "false_complete_reason": FALSE_COMPLETE_REASON,
        "headline": {
            "document_recall_b1": b1.get("document_recall"),
            "leftover_at_b1": b1.get("unresolved_relevant_documents") or [],
            "leftover_at_b2": b2.get("unresolved_relevant_documents") or [],
            "first_complete_budget": treatment_first.get("budget"),
            "baseline_first_complete_budget": baseline_first.get("budget"),
            "first_complete_classified": treatment_first.get("first_complete_classified"),
            "baseline_first_complete_classified": baseline_first.get("first_complete_classified"),
            "classified_b5": b5.get("classified"),
            "baseline_classified_b5": (versus.get("budgets") or [{}])[-1].get("baseline", {}).get(
                "classified"
            ),
            "jev_calls_b5": b5.get("jev_calls"),
            "hop_fetches_b5": b5.get("hop_fetches"),
            "baseline_hop_fetches_b5": (versus.get("budgets") or [{}])[-1]
            .get("baseline", {})
            .get("hop_fetches"),
            "work_after_complete_b3": treatment_first.get("work_after_complete"),
            "baseline_work_after_complete_b3": baseline_first.get("work_after_complete"),
            "false_complete": false_complete,
            "false_complete_count": len(false_complete),
            "avtal_49_falsely_complete": "Avtal_49_IT_drift_hostingavtal.docx" in false_complete,
            "wall_seconds": payload.get("wall_seconds"),
        },
        "budgets": [
            {
                "budget": row.get("budget"),
                "classified": row.get("classified"),
                "jev_calls": row.get("jev_calls"),
                "cache_hits": row.get("cache_hits"),
                "document_recall": row.get("document_recall"),
                "jev_yes_document_recall": row.get("jev_yes_document_recall"),
                "first_complete_classified": row.get("first_complete_classified"),
                "hop_fetches": row.get("hop_fetches"),
                "budget_exhausted_documents": row.get("budget_exhausted_documents"),
                "unresolved_relevant_documents": row.get("unresolved_relevant_documents"),
                "evidence_found_nonrelevant": row.get("evidence_found_nonrelevant") or [],
                "status_counts": row.get("status_counts"),
                "wall_seconds": row.get("wall_seconds"),
            }
            for row in gold.get("budgets") or []
        ],
        "versus_first_complete_evidence": evidence,
        "extra_classifications_are_mostly": "other_document_discovery",
    }


def write_relation_carveout_baseline(
    payload: dict[str, Any],
    path: Path | None = None,
) -> Path:
    target = path or RELATION_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(freeze_relation_carveout_baseline(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def load_relation_carveout_baseline(path: Path | None = None) -> dict[str, Any]:
    target = path or RELATION_BASELINE_PATH
    return json.loads(target.read_text(encoding="utf-8"))
