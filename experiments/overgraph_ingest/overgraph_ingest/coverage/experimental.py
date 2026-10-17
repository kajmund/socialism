"""Freeze Coverage v3 + append on confidentiality as an experimental baseline.

Does not replace official C@8 or Coverage v3. Do not overwrite this file
from later runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from overgraph_ingest.retrieval.expand import EXPANSION_POLICY

EXPERIMENTAL_BASELINE_ID = "phase2-coverage-v3-append-confidentiality"
EXPERIMENTAL_BASELINE_LABEL = (
    "Experimental: deterministic append query expansion plus Coverage v3 "
    "on confidentiality. Not the official classify or coverage baseline."
)
EXPERIMENTAL_BASELINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "baselines"
    / f"{EXPERIMENTAL_BASELINE_ID}.json"
)


def freeze_append_confidentiality_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    versus = payload.get("versus_baseline_v3") or {}
    first = versus.get("first_complete") or {}
    treatment_first = first.get("treatment") or {}
    baseline_first = first.get("baseline") or {}
    golds = list(payload.get("golds") or [])
    gold = next(
        (item for item in golds if item.get("gold_id") == "confidentiality"),
        golds[0] if golds else {},
    )
    budgets = {int(row["budget"]): row for row in gold.get("budgets") or [] if "budget" in row}
    b1 = budgets.get(1) or {}
    b2 = budgets.get(2) or {}
    return {
        "id": EXPERIMENTAL_BASELINE_ID,
        "label": EXPERIMENTAL_BASELINE_LABEL,
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "default_retriever_unchanged": True,
        "expansion_policy": dict(EXPANSION_POLICY),
        "gold_id": "confidentiality",
        "query_variant": "append",
        "controller": "deterministic_v3",
        "classify_unchanged": True,
        "headline": {
            "recall_at_50": gold.get("recall_at_50"),
            "baseline_recall_at_50": versus.get("baseline_recall_at_50"),
            "first_complete_budget": treatment_first.get("budget"),
            "baseline_first_complete_budget": baseline_first.get("budget"),
            "classified": treatment_first.get("classified"),
            "baseline_classified": baseline_first.get("classified"),
            "cumulative_jev_calls": treatment_first.get("cumulative_jev_calls"),
            "baseline_cumulative_jev_calls": baseline_first.get("cumulative_jev_calls"),
            "wall_seconds_to_complete": b2.get("wall_seconds"),
            "baseline_wall_seconds_to_complete": _baseline_complete_wall(versus),
            "false_negative_documents": b2.get("false_negative_documents") or [],
            "budget_exhausted_documents": b2.get("budget_exhausted_documents"),
            "cache_hits_at_b1": b1.get("cache_hits"),
            "leftover_at_b1": b1.get("unresolved_relevant_documents") or [],
        },
        "budgets": [
            {
                "budget": row.get("budget"),
                "classified": row.get("classified"),
                "jev_calls": row.get("jev_calls"),
                "cache_hits": row.get("cache_hits"),
                "document_recall": row.get("document_recall"),
                "jev_yes_document_recall": row.get("jev_yes_document_recall"),
                "budget_exhausted_documents": row.get("budget_exhausted_documents"),
                "unresolved_relevant_documents": row.get("unresolved_relevant_documents"),
                "false_negative_documents": row.get("false_negative_documents"),
                "wall_seconds": row.get("wall_seconds"),
            }
            for row in gold.get("budgets") or []
        ],
        "versus_first_complete": first,
    }


def write_experimental_append_baseline(
    payload: dict[str, Any],
    path: Path | None = None,
) -> Path:
    target = path or EXPERIMENTAL_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(freeze_append_confidentiality_baseline(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def load_experimental_append_baseline(path: Path | None = None) -> dict[str, Any]:
    target = path or EXPERIMENTAL_BASELINE_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def _baseline_complete_wall(versus: dict[str, Any]) -> float | None:
    for row in versus.get("budgets") or []:
        if row.get("budget") == 5:
            seconds = (row.get("baseline") or {}).get("wall_seconds")
            return float(seconds) if seconds is not None else None
    return None
