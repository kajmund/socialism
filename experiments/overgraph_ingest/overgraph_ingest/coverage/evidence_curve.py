"""Evidence curves from frozen C@8 and Coverage v3. No new Jev calls."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.cache import load_c8_judgments
from overgraph_ingest.coverage.v2 import DEFAULT_CACHE

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V3 = ROOT / "data" / "coverage-v3.json"
CHECKPOINTS = (10, 25, 50, 100, 150, 200)
EVIDENCE_CONTRACTS = {
    "document_existence": "first_verified_positive_may_answer",
    "workspace_inventory": "every_document_verified_or_unresolved",
}


def ranking_curve(payload: dict[str, object]) -> dict[str, object]:
    rows = sorted(
        load_c8_judgments(payload),
        key=lambda row: (int(row.get("rank") or 10**9), str(row.get("key") or "")),
    )
    found: list[str] = []
    increments: list[dict[str, object]] = []
    series: list[dict[str, object]] = []
    previous_classified = 0
    for index, row in enumerate(rows, start=1):
        path = str(row.get("relative_path") or "")
        if (
            row.get("gold_label") == "relevant"
            and row.get("predicted") == "YES"
            and path
            and path not in found
        ):
            found.append(path)
            increments.append(
                {
                    "document": path,
                    "classified": index,
                    "cost_since_previous": index - previous_classified,
                    "verified_positive_documents": len(found),
                }
            )
            previous_classified = index
        series.append({"classified": index, "verified_positive_documents": len(found)})
    return {
        "gold_id": payload.get("gold_id"),
        "source": "c8_ranking",
        "candidates": len(rows),
        "verified_positive_documents": len(found),
        "checkpoints": _at_or_before(series, (10, 25, 50)),
        "increments": increments,
        "series": series,
    }


def coverage_curve(gold_row: dict[str, object]) -> dict[str, object]:
    budgets = list(gold_row.get("budgets") or [])
    last = budgets[-1] if budgets else {}
    timeline = list(last.get("timeline") or [])
    series = [
        {
            "phase": point.get("phase"),
            "classified": point.get("classified"),
            "verified_positive_documents": point.get("documents_found"),
        }
        for point in timeline
    ]
    increments = []
    previous_classified = 0
    previous_found = 0
    for point in series:
        classified = int(point["classified"] or 0)
        found = int(point["verified_positive_documents"] or 0)
        gained = found - previous_found
        increments.append(
            {
                "phase": point["phase"],
                "classified": classified,
                "verified_positive_documents": found,
                "new_documents": gained,
                "cost_since_previous": classified - previous_classified,
                "cost_per_new_document": (
                    None if gained <= 0 else (classified - previous_classified) / gained
                ),
            }
        )
        previous_classified = classified
        previous_found = found
    last_gain = next(
        (row for row in reversed(increments) if int(row["new_documents"] or 0) > 0),
        None,
    )
    final_classified = int(last.get("classified") or previous_classified)
    last_gain_at = int(last_gain["classified"]) if last_gain else 0
    return {
        "gold_id": gold_row.get("gold_id"),
        "source": "coverage_v3_last_budget",
        "variant": last.get("variant"),
        "documents_expected": last.get("documents_expected"),
        "verified_positive_documents": last.get("documents_found"),
        "budget_exhausted_documents": last.get("budget_exhausted_documents"),
        "unresolved_relevant_documents": last.get("unresolved_relevant_documents") or [],
        "last_new_positive_at": last_gain_at or None,
        "classifications_after_last_new_positive": final_classified - last_gain_at,
        "checkpoints": _coverage_checkpoints(series, CHECKPOINTS),
        "increments": increments,
        "series": series,
        "budget_exhausted_is_not_absent": True,
    }


def run_evidence_curves(
    *,
    cache_root: Path | None = None,
    coverage_v3_path: Path | None = None,
) -> dict[str, object]:
    root = cache_root or ROOT
    coverage = json.loads((coverage_v3_path or DEFAULT_V3).read_text(encoding="utf-8"))
    coverage_by_id = {item.get("gold_id"): item for item in coverage.get("golds") or []}
    golds = []
    for gold_id, relative in DEFAULT_CACHE.items():
        c8 = json.loads((root / relative).read_text(encoding="utf-8"))
        ranking = ranking_curve(c8)
        ranking["source_path"] = str(relative)
        workspace = coverage_curve(coverage_by_id.get(gold_id) or {})
        golds.append(
            {
                "gold_id": gold_id,
                "ranking": ranking,
                "workspace": workspace,
            }
        )
    return {
        "operation": "coverage",
        "experiment": "evidence_curve_v1",
        "classify_unchanged": True,
        "default_retriever_unchanged": True,
        "does_not_replace_c8": True,
        "do_not_optimize_first_yes": True,
        "budget_exhausted_is_not_absent": True,
        "evidence_contracts": dict(EVIDENCE_CONTRACTS),
        "checkpoints": list(CHECKPOINTS),
        "golds": golds,
    }


def _at_or_before(
    series: list[dict[str, object]], checkpoints: tuple[int, ...]
) -> list[dict[str, object]]:
    rows = []
    for mark in checkpoints:
        chosen = None
        for point in series:
            if int(point["classified"] or 0) <= mark:
                chosen = point
        rows.append(
            {
                "classified": mark,
                "verified_positive_documents": (
                    None if chosen is None else chosen["verified_positive_documents"]
                ),
            }
        )
    return rows


def _coverage_checkpoints(
    series: list[dict[str, object]], checkpoints: tuple[int, ...]
) -> list[dict[str, object]]:
    return _at_or_before(
        [
            {
                "classified": point.get("classified"),
                "verified_positive_documents": point.get("verified_positive_documents"),
            }
            for point in series
        ],
        checkpoints,
    )
