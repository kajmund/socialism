"""Variant D on frozen dense top-5. Hybrid D stays the reference. No navigation."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.conclusions import (
    load_tabular_direct_baseline,
    load_tabular_signals_baseline,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.cells import VARIANT_D, VARIANT_E, answer_without_classify
from overgraph_ingest.tabular.evaluate import FALSE_ANSWER, compare_variants, headline, score_cell, summarize
from overgraph_ingest.tabular.gold import USER_QUESTIONS, cell_relevant_keys, load_tabular_golds
from overgraph_ingest.tabular.run import _load_context
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.serialize import cell_payload

ROOT = Path(__file__).resolve().parents[2]
TABULAR_DENSE_ID = "phase2-tabular-dense-v1"
TABULAR_DENSE_PATH = ROOT / "baselines" / f"{TABULAR_DENSE_ID}.json"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
REFERENCE_VARIANT = VARIANT_D


def run_tabular_dense(
    *,
    signals_path: Path | None = None,
    direct_path: Path | None = None,
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
    signals: dict[str, object] | None = None,
    reference: dict[str, object] | None = None,
    expected_cells: int | None = 100,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    lists = signals or _load_signals(signals_path)
    source = reference or _load_direct(direct_path)
    cells = _signal_cells(lists, expected=expected_cells)
    gold_by_id = {gold.id: gold for gold in golds or load_tabular_golds(gold_dir or DEFAULT_GOLD_DIR)}
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    by_key = graph.by_key()
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for tabular dense")
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
        retrieval = {
            "k": DEFAULT_K,
            "strategy": "dense",
            "candidate_keys": [hit.key for hit in hits],
            "recall@3": 1.0 if relevant and {hit.key for hit in hits[:3]} & relevant else 0.0,
            "recall@5": 1.0 if relevant and {hit.key for hit in hits[:5]} & relevant else 0.0,
            "recall@10": 1.0 if relevant else 0.0,
        }
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
            variant=VARIANT_E,
        )
        results.append(result)
        scored.append(score_cell(result, relevant))
        print(
            f"{VARIANT_E} {result.document_id} {question_id} {result.status}",
            file=sys.stderr,
            flush=True,
        )
    wall = time.perf_counter() - started
    d_scored = [
        row
        for row in source.get("scored") or []
        if isinstance(row, dict) and row.get("variant") == REFERENCE_VARIANT
    ]
    if expected_cells is not None and len(d_scored) != len(scored):
        raise ValueError(f"dense cells must match frozen D: {len(d_scored)} vs {len(scored)}")
    e_summary = summarize(scored)
    d_summary = summarize(d_scored)
    paired = _pair(d_scored, scored)
    misses = _confidentiality_misses(lists)
    recovered = _recovered(paired, misses)
    jev_calls = sum(int(row.get("jev_calls") or 0) for row in scored)
    d_jev = sum(int(row.get("jev_calls") or 0) for row in d_scored)
    cost = {
        "jev_calls": jev_calls,
        "reference_jev_calls": d_jev,
        "classify_calls": 0,
        "answer_calls": jev_calls,
        "cerebras_calls": 0,
        "jev_usd": None,
        "jev_cost_unknown": True,
    }
    return {
        "operation": "tabular_dense",
        "experiment": "tabular_dense_v1",
        "task": "document_local_source_grounded_cell",
        "replay_of": ("phase2-tabular-signals-v1", "phase2-tabular-direct-v1"),
        "performance_reference": REFERENCE_VARIANT,
        "retrieval_baseline": "hybrid",
        "retrieval_treatment": "dense",
        "same_100_cells": expected_cells == 100,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "no_new_model": True,
        "no_new_embedding": True,
        "no_navigation": True,
        "classify_skipped": True,
        "default_k_unchanged": True,
        "default_hybrid_unchanged": True,
        "k": DEFAULT_K,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "does_not_replace_tabular_signals": True,
        "navigation_not_changed": True,
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "synchronous": True,
        "cells": [cell_payload(result) for result in results],
        "scored": scored,
        "dense": e_summary,
        "reference": d_summary,
        "comparison": compare_variants(d_scored + scored),
        "paired": paired,
        "recovered": recovered,
        "versus": {
            "e_vs_d_cell_accuracy": e_summary["cell_accuracy"] - d_summary["cell_accuracy"],
            "e_vs_d_answer_accuracy": e_summary["answer_accuracy"] - d_summary["answer_accuracy"],
            "e_vs_d_citation_accuracy": e_summary["citation_accuracy"]
            - d_summary["citation_accuracy"],
            "e_vs_d_false_answers": e_summary["outcomes"]["false_answer"]
            - d_summary["outcomes"]["false_answer"],
        },
        "headline": {
            **headline(compare_variants(d_scored + scored), cost),
            "performance_reference": REFERENCE_VARIANT,
            "k": DEFAULT_K,
            "dense_cell_accuracy": e_summary["cell_accuracy"],
            "dense_answer_accuracy": e_summary["answer_accuracy"],
            "dense_citation_accuracy": e_summary["citation_accuracy"],
            "reference_cell_accuracy": d_summary["cell_accuracy"],
            "dense_jev_calls": jev_calls,
            "confidentiality_recovered": recovered["recovered_cells"],
            "confidentiality_misses": recovered["confidentiality_misses"],
            "new_gold_negative_false_answers": recovered["new_gold_negative_false_answers"],
            "cell_improvements": recovered["cell_improvements"],
            "cell_regressions": recovered["cell_regressions"],
            "default_hybrid_unchanged": True,
            "default_k_unchanged": True,
        },
        "cost": cost,
        "wall_seconds": wall,
    }


def freeze_tabular_dense(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_DENSE_ID,
        "label": (
            "Frozen: Jev answer_cell on frozen dense top-5 versus hybrid D. "
            "Same 100 diagnostic cells. No navigation. Hybrid stays the "
            "retrieval baseline. Does not replace C@8, Coverage v3, tabular "
            "v1, direct D, or signals."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "does_not_replace_tabular_signals": True,
        "no_new_model": True,
        "no_new_embedding": True,
        "no_navigation": True,
        "default_k_unchanged": True,
        "default_hybrid_unchanged": True,
        "performance_reference": REFERENCE_VARIANT,
        "retrieval_baseline": "hybrid",
        "retrieval_treatment": "dense",
        "same_100_cells": True,
        "same_mapping": GOLD_MAP_VERSION,
        "selection_is_diagnostic": True,
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "dense": payload.get("dense"),
        "reference": payload.get("reference"),
        "recovered": payload.get("recovered"),
        "cost": payload.get("cost"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "paired": payload.get("paired"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_dense_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_DENSE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_dense(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _load_signals(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_signals_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _load_direct(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_direct_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _signal_cells(
    payload: dict[str, object],
    *,
    expected: int | None,
) -> list[dict[str, object]]:
    cells = [row for row in payload.get("cells") or [] if isinstance(row, dict)]
    if expected is not None and len(cells) != expected:
        raise ValueError(f"signals cells must be {expected}, got {len(cells)}")
    return cells


def _hits(row: dict[str, object], by_key: dict[str, StoredUnit]) -> list[SearchHit]:
    dense = row.get("dense") or {}
    keys = [str(key) for key in (dense.get("candidate_keys") or [])]
    if not keys:
        raise ValueError(f"signals cell {row.get('question_id')} is missing dense keys")
    hits = []
    for rank, key in enumerate(keys, start=1):
        unit = by_key.get(key)
        if unit is None:
            raise KeyError(f"dense candidate {key} is missing from the database")
        if unit.relative_path != row["relative_path"]:
            raise ValueError(f"dense candidate {key} leaked another document")
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


def _confidentiality_misses(lists: dict[str, object]) -> list[dict[str, object]]:
    recovered = lists.get("recovered") or {}
    return [row for row in recovered.get("rows") or [] if isinstance(row, dict)]


def _pair(
    reference: list[dict[str, object]],
    treatment: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_e = {(row["relative_path"], row["question_id"]): row for row in treatment}
    paired = []
    for left in reference:
        right = by_e.get((left["relative_path"], left["question_id"]))
        if right is None:
            raise ValueError(
                f"dense is missing {left['relative_path']} {left['question_id']}"
            )
        paired.append(
            {
                "document_id": right.get("document_id") or left.get("document_id"),
                "relative_path": left["relative_path"],
                "question_id": left["question_id"],
                "gold_positive": bool(left["gold_positive"]),
                "d_status": left["status"],
                "e_status": right["status"],
                "d_outcome": left["outcome"],
                "e_outcome": right["outcome"],
                "d_full": bool(left["full_success"]),
                "e_full": bool(right["full_success"]),
                "d_answer": bool(left["answer_correct"]),
                "e_answer": bool(right["answer_correct"]),
                "d_citation": bool(left["citation_relevant"]),
                "e_citation": bool(right["citation_relevant"]),
                "improved_cell": bool(right["full_success"]) and not bool(left["full_success"]),
                "regressed_cell": bool(left["full_success"]) and not bool(right["full_success"]),
            }
        )
    return paired


def _recovered(
    paired: list[dict[str, object]],
    misses: list[dict[str, object]],
) -> dict[str, object]:
    miss_keys = {
        (str(row["relative_path"]), str(row["question_id"])) for row in misses
    }
    miss_pairs = [
        row
        for row in paired
        if (row["relative_path"], row["question_id"]) in miss_keys
    ]
    if misses and len(miss_pairs) != len(miss_keys):
        raise ValueError("dense pairing missed a hybrid confidentiality miss")
    new_false = [
        row
        for row in paired
        if not row["gold_positive"]
        and row["e_outcome"] == FALSE_ANSWER
        and row["d_outcome"] != FALSE_ANSWER
    ]
    return {
        "confidentiality_misses": len(miss_pairs),
        "recovered_cells": sum(1 for row in miss_pairs if row["improved_cell"]),
        "recovered_answers": sum(1 for row in miss_pairs if row["e_answer"] and not row["d_answer"]),
        "recovered_citations": sum(
            1 for row in miss_pairs if row["e_citation"] and not row["d_citation"]
        ),
        "still_failed": sum(1 for row in miss_pairs if not row["e_full"]),
        "new_gold_negative_false_answers": len(new_false),
        "cell_improvements": sum(1 for row in paired if row["improved_cell"]),
        "cell_regressions": sum(1 for row in paired if row["regressed_cell"]),
        "missing_rows": miss_pairs,
        "new_false_rows": new_false,
    }
