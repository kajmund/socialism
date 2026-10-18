"""Freeze Coverage v3 + linked-relation proof. Does not replace v3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from overgraph_ingest.coverage.compare import gold_row

LINK_COVERAGE_BASELINE_ID = "phase2-coverage-v3-link-carveout"
LINK_COVERAGE_BASELINE_LABEL = (
    "Experimental: Coverage v3 with source-grounded relation proof on "
    "liability-secrecy-carveout. Not the default controller."
)
LINK_COVERAGE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{LINK_COVERAGE_BASELINE_ID}.json"
)


def freeze_link_carveout_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    versus = payload.get("versus_baseline_v3") or {}
    evidence = versus.get("first_complete_evidence") or {}
    treatment_first = evidence.get("treatment") or {}
    baseline_first = evidence.get("baseline") or {}
    gold = gold_row(payload, "liability-secrecy-carveout")
    budgets = {
        int(row["budget"]): row for row in gold.get("budgets") or [] if row.get("budget") is not None
    }
    b1 = budgets.get(1) or {}
    b5 = budgets.get(5) or {}
    false_complete = list(b5.get("evidence_found_nonrelevant") or [])
    return {
        "id": LINK_COVERAGE_BASELINE_ID,
        "label": LINK_COVERAGE_BASELINE_LABEL,
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "ready_for_default_controller": False,
        "controller": "deterministic_v3",
        "proof_rule": "link",
        "classify_unchanged": True,
        "default_retriever_unchanged": True,
        "discovery_unchanged": True,
        "gold_id": "liability-secrecy-carveout",
        "headline": {
            "document_recall_b1": b1.get("document_recall"),
            "leftover_at_b1": b1.get("unresolved_relevant_documents") or [],
            "first_complete_budget": treatment_first.get("budget"),
            "baseline_first_complete_budget": baseline_first.get("budget"),
            "first_complete_classified": treatment_first.get("first_complete_classified"),
            "baseline_first_complete_classified": baseline_first.get(
                "first_complete_classified"
            ),
            "classified_b5": b5.get("classified"),
            "baseline_classified_b5": (versus.get("budgets") or [{}])[-1]
            .get("baseline", {})
            .get("classified"),
            "jev_calls_b5": b5.get("jev_calls"),
            "hop_fetches_b5": b5.get("hop_fetches"),
            "work_after_complete": treatment_first.get("work_after_complete"),
            "baseline_work_after_complete": baseline_first.get("work_after_complete"),
            "false_complete": false_complete,
            "false_complete_count": len(false_complete),
            "budget_exhausted_documents": b5.get("budget_exhausted_documents"),
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
        "zero_false_complete": len(false_complete) == 0,
    }


def write_link_carveout_baseline(
    payload: dict[str, Any],
    path: Path | None = None,
) -> Path:
    target = path or LINK_COVERAGE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(freeze_link_carveout_baseline(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def load_link_carveout_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or LINK_COVERAGE_BASELINE_PATH).read_text(encoding="utf-8"))
