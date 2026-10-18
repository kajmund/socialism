"""Jev Tabular B at k=10 versus frozen B at k=5. No new model. No navigation."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.cerebras.client import Completer
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.jev.client import JevClient
from overgraph_ingest.retrieval.conclusions import (
    load_tabular_citation_baseline,
    load_tabular_review_baseline,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.cells import VARIANT_B, VARIANT_K
from overgraph_ingest.tabular.citation import gold_hit
from overgraph_ingest.tabular.evaluate import compare_variants, headline, summarize
from overgraph_ingest.tabular.gold import SELECTED_DOCUMENTS
from overgraph_ingest.tabular.run import run_tabular_review
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[2]
TABULAR_K10_ID = "phase2-tabular-k10-v1"
TABULAR_K10_PATH = ROOT / "baselines" / f"{TABULAR_K10_ID}.json"
K10 = 10
REFERENCE_VARIANT = VARIANT_B


def run_tabular_k10(
    *,
    frozen_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    dense_model: str = "text-embedding-3-large",
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]] | None = None,
    golds: list[RetrievalGold] | None = None,
    documents: tuple[str, ...] | None = None,
    jev: JevClient | None = None,
    cerebras: Completer | None = None,
    context: GraphContext | None = None,
    frozen: dict[str, object] | None = None,
    citation: dict[str, object] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    live = run_tabular_review(
        db_path=db_path,
        gold_dir=gold_dir,
        dense_dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        dense_model=dense_model,
        typesafe_api_key=typesafe_api_key,
        typesafe_base_url=typesafe_base_url,
        jev_model=jev_model,
        jev_timeout_seconds=jev_timeout_seconds,
        documents=documents or SELECTED_DOCUMENTS,
        variants=(VARIANT_K,),
        top_k=K10,
        units=units,
        structures=structures,
        queries=queries,
        golds=golds,
        jev=jev,
        cerebras=cerebras,
        context=context,
    )
    source = frozen or _load_review(frozen_path)
    used = tuple(documents or SELECTED_DOCUMENTS)
    b_scored = [
        row
        for row in _variant_rows(source.get("scored") or [], REFERENCE_VARIANT)
        if row.get("relative_path") in used
    ]
    k_scored = _variant_rows(live.get("scored") or [], VARIANT_K)
    if len(b_scored) != len(k_scored):
        raise ValueError(f"k=10 cells must match frozen B: {len(b_scored)} vs {len(k_scored)}")
    compared = compare_variants(b_scored + k_scored)
    k_summary = summarize(k_scored)
    b_summary = summarize(b_scored)
    paired = _pair(b_scored, k_scored)
    missing = _missing_from(citation)
    recovered = _recovered(paired, missing)
    cost = dict(live.get("cost") or {})
    return {
        "operation": "tabular_k10",
        "experiment": "tabular_k10_v1",
        "task": "document_local_source_grounded_cell",
        "replay_of": "phase2-tabular-review-v1",
        "quality_reference": REFERENCE_VARIANT,
        "same_100_cells": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "no_new_model": True,
        "no_navigation": True,
        "default_k_unchanged": True,
        "reference_k": DEFAULT_K,
        "k": K10,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_citation": True,
        "navigation_not_changed": True,
        "model_comparisons_paused": True,
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "synchronous": True,
        "cells": live.get("cells"),
        "scored": k_scored,
        "k10": k_summary,
        "reference": b_summary,
        "comparison": compared,
        "paired": paired,
        "recovered": recovered,
        "versus": {
            "k_vs_b_cell_accuracy": k_summary["cell_accuracy"] - b_summary["cell_accuracy"],
            "k_vs_b_answer_accuracy": k_summary["answer_accuracy"] - b_summary["answer_accuracy"],
            "k_vs_b_citation_accuracy": k_summary["citation_accuracy"]
            - b_summary["citation_accuracy"],
        },
        "headline": {
            **headline(compared, cost),
            "quality_reference": REFERENCE_VARIANT,
            "k": K10,
            "reference_k": DEFAULT_K,
            "k10_cell_accuracy": k_summary["cell_accuracy"],
            "k10_answer_accuracy": k_summary["answer_accuracy"],
            "k10_citation_accuracy": k_summary["citation_accuracy"],
            "recovered_missing_gold": recovered["recovered_cells"],
            "recoverable_at_k10": recovered["recoverable_at_k10"],
            "still_missing_at_k10": recovered["still_missing_at_k10"],
            "new_gold_negative_false_answers": recovered["new_gold_negative_false_answers"],
            "default_k_unchanged": True,
        },
        "cost": cost,
        "wall_seconds": live.get("wall_seconds"),
    }


def freeze_tabular_k10(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_K10_ID,
        "label": (
            "Frozen: Jev Tabular B at k=10 versus frozen B at k=5. Same "
            "100 diagnostic cells. No new model and no navigation. Does "
            "not replace C@8, Coverage v3, tabular v1, or citation v1. "
            "Default k stays 5 until this measurement is read."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_citation": True,
        "navigation_not_changed": True,
        "model_comparisons_paused": True,
        "default_k_unchanged": True,
        "quality_reference": REFERENCE_VARIANT,
        "same_100_cells": True,
        "no_new_model": True,
        "no_navigation": True,
        "k": K10,
        "reference_k": DEFAULT_K,
        "same_mapping": GOLD_MAP_VERSION,
        "selection_is_diagnostic": True,
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "k10": payload.get("k10"),
        "reference": payload.get("reference"),
        "recovered": payload.get("recovered"),
        "cost": payload.get("cost"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_k10_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_K10_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_k10(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _load_review(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_review_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _missing_from(citation: dict[str, object] | None) -> list[dict[str, object]]:
    source = citation if citation is not None else load_tabular_citation_baseline()
    rows = source.get("missing_cells") or []
    return [row for row in rows if isinstance(row, dict)]


def _variant_rows(rows: list[object], variant: str) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if isinstance(row, dict) and row.get("variant") == variant
    ]


def _pair(
    reference: list[dict[str, object]],
    treatment: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_k = {(row["relative_path"], row["question_id"]): row for row in treatment}
    paired: list[dict[str, object]] = []
    for left in reference:
        right = by_k.get((left["relative_path"], left["question_id"]))
        if right is None:
            raise ValueError(
                f"k=10 is missing {left['relative_path']} {left['question_id']}"
            )
        paired.append(
            {
                "document_id": right.get("document_id") or left.get("document_id"),
                "relative_path": left["relative_path"],
                "question_id": left["question_id"],
                "gold_positive": bool(left["gold_positive"]),
                "b_seed_has_gold": bool(left.get("seed_has_gold")),
                "k_seed_has_gold": bool(right.get("seed_has_gold")),
                "gold_in_k10": gold_hit(right.get("recall@10")),
                "b_status": left["status"],
                "k_status": right["status"],
                "b_outcome": left["outcome"],
                "k_outcome": right["outcome"],
                "b_full": bool(left["full_success"]),
                "k_full": bool(right["full_success"]),
                "b_answer": bool(left["answer_correct"]),
                "k_answer": bool(right["answer_correct"]),
                "b_citation": bool(left["citation_relevant"]),
                "k_citation": bool(right["citation_relevant"]),
                "improved_cell": bool(right["full_success"]) and not bool(left["full_success"]),
                "regressed_cell": bool(left["full_success"]) and not bool(right["full_success"]),
            }
        )
    return paired


def _recovered(
    paired: list[dict[str, object]],
    missing: list[dict[str, object]],
) -> dict[str, object]:
    missing_keys = {
        (str(row["relative_path"]), str(row["question_id"])) for row in missing
    }
    missing_pairs = [
        row
        for row in paired
        if (row["relative_path"], row["question_id"]) in missing_keys
    ]
    if missing and len(missing_pairs) != len(missing_keys):
        raise ValueError("k=10 pairing missed a citation-missing gold cell")
    new_false = [
        row
        for row in paired
        if not row["gold_positive"]
        and row["k_outcome"] == "false_answer"
        and row["b_outcome"] != "false_answer"
    ]
    return {
        "missing_gold_at_k5": len(missing_pairs),
        "recoverable_at_k10": sum(1 for row in missing_pairs if row["gold_in_k10"]),
        "present_at_k10": sum(1 for row in missing_pairs if row["k_seed_has_gold"]),
        "recovered_cells": sum(1 for row in missing_pairs if row["improved_cell"]),
        "recovered_answers": sum(1 for row in missing_pairs if row["k_answer"] and not row["b_answer"]),
        "recovered_citations": sum(
            1 for row in missing_pairs if row["k_citation"] and not row["b_citation"]
        ),
        "still_missing_at_k10": sum(1 for row in missing_pairs if not row["gold_in_k10"]),
        "still_failed_when_present": sum(
            1
            for row in missing_pairs
            if row["k_seed_has_gold"] and not row["k_full"]
        ),
        "new_gold_negative_false_answers": len(new_false),
        "cell_improvements": sum(1 for row in paired if row["improved_cell"]),
        "cell_regressions": sum(1 for row in paired if row["regressed_cell"]),
        "missing_rows": missing_pairs,
        "new_false_rows": new_false,
    }
