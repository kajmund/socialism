"""Dense vs sparse vs hybrid on the same document-local units. No model answers."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.conclusions import (
    load_tabular_citation_baseline,
    load_tabular_review_baseline,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.direct import frozen_b_cells
from overgraph_ingest.tabular.gold import (
    QUESTION_IDS,
    SELECTED_DOCUMENTS,
    USER_QUESTIONS,
    cell_relevant_keys,
    load_tabular_golds,
)
from overgraph_ingest.tabular.run import _encode_questions, _load_context
from overgraph_ingest.tabular.search import DEFAULT_K, STRATEGIES, document_local_ranks, recall_at

ROOT = Path(__file__).resolve().parents[2]
TABULAR_SIGNALS_ID = "phase2-tabular-signals-v1"
TABULAR_SIGNALS_PATH = ROOT / "baselines" / f"{TABULAR_SIGNALS_ID}.json"
DEFAULT_DB = ROOT / "data" / "extra-overgraph-phase2"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
BASELINE = "hybrid"


def run_tabular_signals(
    *,
    frozen_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    dense_model: str = "text-embedding-3-large",
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]] | None = None,
    golds: list[RetrievalGold] | None = None,
    documents: tuple[str, ...] | None = None,
    frozen: dict[str, object] | None = None,
    citation: dict[str, object] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    used = tuple(documents or SELECTED_DOCUMENTS)
    source = frozen or _load_review(frozen_path)
    cells = [
        row
        for row in frozen_b_cells(source, expected=None)
        if row.get("relative_path") in used
    ]
    if not cells:
        raise ValueError("no frozen B cells for the requested documents")
    gold_rows = golds or load_tabular_golds(gold_dir or DEFAULT_GOLD_DIR)
    gold_by_id = {gold.id: gold for gold in gold_rows}
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    encoded = queries or _encode_questions(
        db_path=db_path or DEFAULT_DB,
        dense_dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        dense_model=dense_model,
        units=graph.units,
    )
    rows = [_cell(row, graph, gold_by_id, encoded) for row in cells]
    gold_pos = [row for row in rows if row["gold_positive"]]
    strategies = {name: _strategy(gold_pos, name) for name in STRATEGIES}
    confidentiality = _question(gold_pos, "confidentiality")
    recovered = _recovered(gold_pos)
    matches = sum(1 for row in rows if row["hybrid_matches_frozen"])
    warranted = _warranted(strategies, confidentiality)
    cited = citation if citation is not None else (
        load_tabular_citation_baseline() if used == SELECTED_DOCUMENTS else {}
    )
    return {
        "operation": "tabular_signals",
        "experiment": "tabular_signals_v1",
        "task": "document_local_signal_lists",
        "replay_of": "phase2-tabular-review-v1",
        "performance_reference": "jev_d",
        "historical_two_step": "jev_b",
        "retrieval_baseline": BASELINE,
        "same_100_cells": used == SELECTED_DOCUMENTS and len(rows) == 100,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "no_new_model": True,
        "no_new_algorithm": True,
        "no_answer_cell": True,
        "no_navigation": True,
        "no_new_retrieval": True,
        "classify_skipped": True,
        "default_k_unchanged": True,
        "k": DEFAULT_K,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "navigation_not_changed": True,
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "cells": rows,
        "gold_positive_cells": len(gold_pos),
        "strategies": strategies,
        "confidentiality": confidentiality,
        "recovered": recovered,
        "hybrid_matches_frozen": matches,
        "hybrid_match_rate": matches / len(rows) if rows else 0.0,
        "answer_cell_warranted": warranted,
        "citation_hybrid_hit@5": (cited.get("retrieval") or {}).get("gold_hit@5_count"),
        "citation_hybrid_hit@10": (cited.get("retrieval") or {}).get("gold_hit@10_count"),
        "headline": {
            "gold_hit@5": {name: strategies[name]["gold_hit@5"] for name in STRATEGIES},
            "gold_hit@10": {name: strategies[name]["gold_hit@10"] for name in STRATEGIES},
            "gold_hit@5_count": {
                name: strategies[name]["gold_hit@5_count"] for name in STRATEGIES
            },
            "gold_hit@10_count": {
                name: strategies[name]["gold_hit@10_count"] for name in STRATEGIES
            },
            "confidentiality_hit@5": {
                name: confidentiality[name]["gold_hit@5"] for name in STRATEGIES
            },
            "confidentiality_hit@5_count": {
                name: confidentiality[name]["gold_hit@5_count"] for name in STRATEGIES
            },
            "hybrid_misses_at_k5": recovered["hybrid_misses_at_k5"],
            "dense_recovers_hybrid_miss": recovered["dense_recovers"],
            "sparse_recovers_hybrid_miss": recovered["sparse_recovers"],
            "hybrid_matches_frozen": matches,
            "answer_cell_warranted": warranted,
            "no_answer_cell": True,
            "default_k_unchanged": True,
        },
    }


def freeze_tabular_signals(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_SIGNALS_ID,
        "label": (
            "Frozen: document-local dense vs sparse vs hybrid lists on the "
            "same 100 diagnostic cells. No answer_cell. No new algorithm. "
            "Does not replace C@8, Coverage v3, tabular v1, or direct D. "
            "Default k stays 5."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "no_new_model": True,
        "no_new_algorithm": True,
        "no_answer_cell": True,
        "no_navigation": True,
        "default_k_unchanged": True,
        "performance_reference": "jev_d",
        "retrieval_baseline": BASELINE,
        "same_100_cells": True,
        "same_mapping": GOLD_MAP_VERSION,
        "selection_is_diagnostic": True,
        "headline": payload.get("headline"),
        "strategies": payload.get("strategies"),
        "confidentiality": payload.get("confidentiality"),
        "recovered": payload.get("recovered"),
        "answer_cell_warranted": payload.get("answer_cell_warranted"),
        "hybrid_matches_frozen": payload.get("hybrid_matches_frozen"),
        "cells": payload.get("cells"),
        "gold_positive_cells": payload.get("gold_positive_cells"),
    }


def write_tabular_signals_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_SIGNALS_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_signals(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _load_review(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_review_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _cell(
    row: dict[str, object],
    graph: GraphContext,
    golds: dict[str, RetrievalGold],
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]],
) -> dict[str, object]:
    question_id = str(row["question_id"])
    relative_path = str(row["relative_path"])
    gold = golds[question_id]
    relevant = cell_relevant_keys(graph.units, gold, relative_path)
    dense_query, sparse_query = queries[question_id]
    ranked = document_local_ranks(
        graph.units,
        relative_path,
        dense_query=dense_query,
        sparse_query=sparse_query,
    )
    frozen_keys = [str(key) for key in ((row.get("retrieval") or {}).get("candidate_keys") or [])]
    hybrid_keys = [hit.key for hit in ranked["hybrid"][:DEFAULT_K]]
    payload = {
        "document_id": row.get("document_id"),
        "relative_path": relative_path,
        "question_id": question_id,
        "question": row.get("question") or USER_QUESTIONS[question_id],
        "gold_positive": bool(relevant),
        "relevant_keys": sorted(relevant),
        "frozen_keys": frozen_keys,
        "hybrid_matches_frozen": hybrid_keys == frozen_keys,
    }
    for name, hits in ranked.items():
        payload[name] = _list(hits, relevant)
    return payload


def _list(hits: list[SearchHit], relevant: set[str]) -> dict[str, object]:
    keys = [hit.key for hit in hits]
    top5 = keys[:DEFAULT_K]
    return {
        "candidate_keys": top5,
        "keys@10": keys[:10],
        "gold_rank": _gold_rank(hits, relevant),
        **recall_at(hits, relevant),
        "hit@5": bool(relevant) and bool(set(top5) & relevant),
        "hit@10": bool(relevant) and bool(set(keys[:10]) & relevant),
    }


def _gold_rank(hits: list[SearchHit], relevant: set[str]) -> int | None:
    for hit in hits:
        if hit.key in relevant:
            return hit.rank
    return None


def _strategy(gold_pos: list[dict[str, object]], name: str) -> dict[str, object]:
    n = len(gold_pos)
    hit5 = sum(1 for row in gold_pos if row[name]["hit@5"])
    hit10 = sum(1 for row in gold_pos if row[name]["hit@10"])
    by_question = {
        question_id: _counts(
            [row for row in gold_pos if row["question_id"] == question_id],
            name,
        )
        for question_id in QUESTION_IDS
    }
    return {
        "cells": n,
        "gold_hit@5": (hit5 / n) if n else 0.0,
        "gold_hit@10": (hit10 / n) if n else 0.0,
        "gold_hit@5_count": hit5,
        "gold_hit@10_count": hit10,
        "missing_at_k5": n - hit5,
        "missing_at_k10": n - hit10,
        "by_question": by_question,
    }


def _question(gold_pos: list[dict[str, object]], question_id: str) -> dict[str, object]:
    rows = [row for row in gold_pos if row["question_id"] == question_id]
    return {name: _strategy(rows, name) for name in STRATEGIES}


def _counts(rows: list[dict[str, object]], name: str) -> dict[str, int]:
    return {
        "gold_positive": len(rows),
        "gold_hit@5": sum(1 for row in rows if row[name]["hit@5"]),
        "gold_hit@10": sum(1 for row in rows if row[name]["hit@10"]),
    }


def _recovered(gold_pos: list[dict[str, object]]) -> dict[str, object]:
    misses = [row for row in gold_pos if not row["hybrid"]["hit@5"]]
    return {
        "hybrid_misses_at_k5": len(misses),
        "hybrid_misses_are_confidentiality": bool(misses)
        and all(row["question_id"] == "confidentiality" for row in misses),
        "dense_recovers": sum(1 for row in misses if row["dense"]["hit@5"]),
        "sparse_recovers": sum(1 for row in misses if row["sparse"]["hit@5"]),
        "rows": [
            {
                "relative_path": row["relative_path"],
                "question_id": row["question_id"],
                "hybrid_gold_rank": row["hybrid"]["gold_rank"],
                "dense_gold_rank": row["dense"]["gold_rank"],
                "sparse_gold_rank": row["sparse"]["gold_rank"],
                "dense_hit@5": row["dense"]["hit@5"],
                "sparse_hit@5": row["sparse"]["hit@5"],
            }
            for row in misses
        ],
    }


def _warranted(
    strategies: dict[str, dict[str, object]],
    confidentiality: dict[str, dict[str, object]],
) -> bool:
    hybrid5 = strategies[BASELINE]["gold_hit@5_count"]
    hybrid_conf = confidentiality[BASELINE]["gold_hit@5_count"]
    for name in ("dense", "sparse"):
        better_all = strategies[name]["gold_hit@5_count"] > hybrid5
        better_conf = (
            confidentiality[name]["gold_hit@5_count"] > hybrid_conf
            and strategies[name]["gold_hit@5_count"] >= hybrid5
        )
        if better_all or better_conf:
            return True
    return False
