"""Jev work along a frozen C@8 ranking. No new model. Completeness stays unsolved."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.cache import load_c8_judgments
from overgraph_ingest.coverage.v2 import DEFAULT_CACHE

ROOT = Path(__file__).resolve().parents[2]


def analysis_cost_from_c8(payload: dict[str, object]) -> dict[str, object]:
    rows = sorted(
        load_c8_judgments(payload),
        key=lambda row: (int(row.get("rank") or 10**9), str(row.get("key") or "")),
    )
    first_relevant = _first(rows, lambda row: row.get("gold_label") == "relevant")
    first_verified = _first(
        rows,
        lambda row: row.get("gold_label") == "relevant" and row.get("predicted") == "YES",
    )
    first_yes = _first(rows, lambda row: row.get("predicted") == "YES")
    first_hard = _first(
        rows,
        lambda row: row.get("gold_label") in {"hard_negative", "watch_negative"},
    )
    stop_rank = first_verified.get("rank") if first_verified else None
    before = [row for row in rows if stop_rank is not None and int(row["rank"]) < int(stop_rank)]
    return {
        "gold_id": payload.get("gold_id"),
        "candidates": len(rows),
        "first_relevant_rank": first_relevant.get("rank") if first_relevant else None,
        "first_verified_positive_rank": first_verified.get("rank") if first_verified else None,
        "first_verified_positive_path": first_verified.get("relative_path") if first_verified else None,
        "first_jev_yes_rank": first_yes.get("rank") if first_yes else None,
        "first_hard_or_watch_rank": first_hard.get("rank") if first_hard else None,
        "judgments_until_first_verified": (
            sum(1 for row in rows if int(row["rank"]) <= int(stop_rank)) if stop_rank is not None else None
        ),
        "false_yes_before_first_verified": sum(1 for row in before if row.get("predicted") == "YES"),
        "hard_or_watch_before_first_verified": sum(
            1 for row in before if row.get("gold_label") in {"hard_negative", "watch_negative"}
        ),
        "uncertain_before_first_verified": sum(1 for row in before if row.get("predicted") == "UNCERTAIN"),
        "budget_exhausted_is_not_absent": True,
    }


def run_analysis_cost(*, cache_root: Path | None = None) -> dict[str, object]:
    root = cache_root or ROOT
    golds = []
    for gold_id, relative in DEFAULT_CACHE.items():
        path = root / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        row = analysis_cost_from_c8(payload)
        row["source"] = str(relative)
        golds.append(row)
    return {
        "operation": "classify",
        "experiment": "analysis_cost_v1",
        "classify_unchanged": True,
        "default_retriever_unchanged": True,
        "does_not_replace_c8": True,
        "budget_exhausted_is_not_absent": True,
        "golds": golds,
    }


def _first(rows: list[dict[str, object]], match) -> dict[str, object] | None:
    for row in rows:
        if match(row):
            return row
    return None
