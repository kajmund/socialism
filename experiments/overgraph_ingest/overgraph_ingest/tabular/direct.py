"""One answer_cell after frozen B k=5 keys. No classify. No navigation."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import GraphContext, context_from_units, load_graph_context
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.conclusions import load_tabular_review_baseline
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.cells import VARIANT_B, VARIANT_D, answer_without_classify
from overgraph_ingest.tabular.evaluate import compare_variants, headline, score_cell, summarize
from overgraph_ingest.tabular.gold import USER_QUESTIONS, cell_relevant_keys, load_tabular_golds
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.serialize import cell_payload

ROOT = Path(__file__).resolve().parents[2]
TABULAR_DIRECT_ID = "phase2-tabular-direct-v1"
TABULAR_DIRECT_PATH = ROOT / "baselines" / f"{TABULAR_DIRECT_ID}.json"
DEFAULT_DB = ROOT / "data" / "extra-overgraph-phase2"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
REFERENCE_VARIANT = VARIANT_B


def frozen_b_cells(
    payload: dict[str, object],
    *,
    expected: int | None = 100,
) -> list[dict[str, object]]:
    cells = [
        row
        for row in payload.get("cells") or []
        if isinstance(row, dict) and row.get("variant") == REFERENCE_VARIANT
    ]
    if expected is not None and len(cells) != expected:
        raise ValueError(f"frozen tabular B cells must be {expected}, got {len(cells)}")
    return cells


def run_tabular_direct(
    *,
    frozen_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    jev: JevClient | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    golds: list[RetrievalGold] | None = None,
    frozen: dict[str, object] | None = None,
    expected_cells: int | None = 100,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    source = frozen or _load_frozen(frozen_path)
    cells = frozen_b_cells(source, expected=expected_cells)
    gold_by_id = {gold.id: gold for gold in golds or load_tabular_golds(gold_dir or DEFAULT_GOLD_DIR)}
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    by_key = graph.by_key()
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for tabular direct")
    client = jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    started = time.perf_counter()
    results = []
    scored = []
    for row in cells:
        question_id = str(row["question_id"])
        relative_path = str(row["relative_path"])
        gold = gold_by_id[question_id]
        relevant = cell_relevant_keys(graph.units, gold, relative_path)
        hits = _hits(row, by_key)
        retrieval = dict(row.get("retrieval") or {})
        retrieval["candidate_keys"] = [hit.key for hit in hits]
        retrieval["k"] = DEFAULT_K
        result = answer_without_classify(
            relative_path=relative_path,
            question_id=question_id,
            user_question=str(row.get("question") or USER_QUESTIONS[question_id]),
            context=graph,
            seeds=hits,
            jev=client,
            jev_model=jev_model,
            timeout_seconds=jev_timeout_seconds,
            retrieve_seconds=0.0,
            retrieval=retrieval,
        )
        results.append(result)
        scored.append(score_cell(result, relevant))
        print(
            f"{VARIANT_D} {result.document_id} {question_id} {result.status}",
            file=sys.stderr,
            flush=True,
        )
    wall = time.perf_counter() - started
    b_scored = [
        row
        for row in source.get("scored") or []
        if isinstance(row, dict) and row.get("variant") == REFERENCE_VARIANT
    ]
    if expected_cells is not None and len(b_scored) != len(scored):
        raise ValueError(f"direct cells must match frozen B: {len(b_scored)} vs {len(scored)}")
    compared = compare_variants(b_scored + scored)
    d_summary = summarize(scored)
    b_summary = summarize(b_scored)
    paired = _pair(b_scored, scored)
    jev_calls = sum(int(row.get("jev_calls") or 0) for row in scored)
    b_jev = sum(int(row.get("jev_calls") or 0) for row in b_scored)
    cost = {
        "jev_calls": jev_calls,
        "reference_jev_calls": b_jev,
        "jev_calls_saved": b_jev - jev_calls,
        "classify_calls": 0,
        "answer_calls": jev_calls,
        "cerebras_calls": 0,
        "jev_usd": None,
        "jev_cost_unknown": True,
    }
    return {
        "operation": "tabular_direct",
        "experiment": "tabular_direct_v1",
        "task": "document_local_source_grounded_cell",
        "replay_of": "phase2-tabular-review-v1",
        "quality_reference": REFERENCE_VARIANT,
        "hypothesis": "A",
        "judgments_passed_to_answer": False,
        "same_100_cells": expected_cells == 100,
        "same_five_candidates": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "no_new_model": True,
        "no_navigation": True,
        "no_new_retrieval": True,
        "classify_skipped": True,
        "default_k_unchanged": True,
        "reference_k": DEFAULT_K,
        "k": DEFAULT_K,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_citation": True,
        "does_not_replace_tabular_k10": True,
        "navigation_not_changed": True,
        "model_comparisons_paused": True,
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "synchronous": True,
        "cells": [cell_payload(result) for result in results],
        "scored": scored,
        "direct": d_summary,
        "reference": b_summary,
        "comparison": compared,
        "paired": paired,
        "versus": {
            "d_vs_b_cell_accuracy": d_summary["cell_accuracy"] - b_summary["cell_accuracy"],
            "d_vs_b_answer_accuracy": d_summary["answer_accuracy"] - b_summary["answer_accuracy"],
            "d_vs_b_citation_accuracy": d_summary["citation_accuracy"]
            - b_summary["citation_accuracy"],
            "d_vs_b_jev_calls": jev_calls - b_jev,
        },
        "headline": {
            **headline(compared, cost),
            "quality_reference": REFERENCE_VARIANT,
            "k": DEFAULT_K,
            "direct_cell_accuracy": d_summary["cell_accuracy"],
            "direct_answer_accuracy": d_summary["answer_accuracy"],
            "direct_citation_accuracy": d_summary["citation_accuracy"],
            "direct_jev_calls": jev_calls,
            "reference_jev_calls": b_jev,
            "cell_improvements": sum(1 for row in paired if row["improved_cell"]),
            "cell_regressions": sum(1 for row in paired if row["regressed_cell"]),
            "same_status": sum(1 for row in paired if row["same_status"]),
            "classify_skipped": True,
            "judgments_passed_to_answer": False,
            "default_k_unchanged": True,
        },
        "cost": cost,
        "wall_seconds": wall,
    }


def freeze_tabular_direct(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_DIRECT_ID,
        "label": (
            "Frozen: one Jev answer_cell on frozen B k=5 keys versus two-step B. "
            "Same 100 diagnostic cells. Classify skipped. No navigation. Does "
            "not replace C@8, Coverage v3, tabular v1, citation v1, or k=10. "
            "Default B and default k stay until this measurement is read."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_citation": True,
        "does_not_replace_tabular_k10": True,
        "navigation_not_changed": True,
        "model_comparisons_paused": True,
        "default_k_unchanged": True,
        "classify_skipped": True,
        "judgments_passed_to_answer": False,
        "hypothesis": "A",
        "quality_reference": REFERENCE_VARIANT,
        "same_100_cells": True,
        "same_five_candidates": True,
        "no_new_model": True,
        "no_navigation": True,
        "no_new_retrieval": True,
        "k": DEFAULT_K,
        "same_mapping": GOLD_MAP_VERSION,
        "selection_is_diagnostic": True,
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "direct": payload.get("direct"),
        "reference": payload.get("reference"),
        "cost": payload.get("cost"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "paired": payload.get("paired"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_direct_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_DIRECT_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_direct(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _load_frozen(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_review_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _load_context(
    *,
    db_path: Path | None,
    dense_dimension: int,
    units: list[StoredUnit] | None,
    structures: dict[str, dict[str, object]] | None,
) -> GraphContext:
    if units is not None:
        return context_from_units(units, structures or {})
    target = db_path or DEFAULT_DB
    dimension = resolve_dimension(target, dense_dimension)
    db = open_database(target, dimension)
    try:
        return load_graph_context(GraphWriter(db, batch_size=500))
    finally:
        db.close()


def _hits(row: dict[str, object], by_key: dict[str, StoredUnit]) -> list[SearchHit]:
    keys = [str(key) for key in ((row.get("retrieval") or {}).get("candidate_keys") or [])]
    if not keys:
        raise ValueError(f"frozen cell {row.get('question_id')} is missing candidate keys")
    hits = []
    for rank, key in enumerate(keys, start=1):
        unit = by_key.get(key)
        if unit is None:
            raise KeyError(f"frozen candidate {key} is missing from the database")
        if unit.relative_path != row["relative_path"]:
            raise ValueError(f"frozen candidate {key} leaked another document")
        hits.append(
            SearchHit(
                node_id=unit.node_id,
                key=unit.key,
                score=0.0,
                rank=rank,
                document_id=unit.document_id,
                relative_path=unit.relative_path,
                text=unit.text,
            )
        )
    return hits


def _pair(
    reference: list[dict[str, object]],
    treatment: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_d = {(row["relative_path"], row["question_id"]): row for row in treatment}
    paired = []
    for left in reference:
        right = by_d.get((left["relative_path"], left["question_id"]))
        if right is None:
            raise ValueError(
                f"direct is missing {left['relative_path']} {left['question_id']}"
            )
        paired.append(
            {
                "document_id": right.get("document_id") or left.get("document_id"),
                "relative_path": left["relative_path"],
                "question_id": left["question_id"],
                "gold_positive": bool(left["gold_positive"]),
                "b_status": left["status"],
                "d_status": right["status"],
                "same_status": left["status"] == right["status"],
                "b_outcome": left["outcome"],
                "d_outcome": right["outcome"],
                "b_full": bool(left["full_success"]),
                "d_full": bool(right["full_success"]),
                "b_answer": bool(left["answer_correct"]),
                "d_answer": bool(right["answer_correct"]),
                "b_citation": bool(left["citation_relevant"]),
                "d_citation": bool(right["citation_relevant"]),
                "b_jev_calls": int(left.get("jev_calls") or 0),
                "d_jev_calls": int(right.get("jev_calls") or 0),
                "improved_cell": bool(right["full_success"]) and not bool(left["full_success"]),
                "regressed_cell": bool(left["full_success"]) and not bool(right["full_success"]),
            }
        )
    return paired
