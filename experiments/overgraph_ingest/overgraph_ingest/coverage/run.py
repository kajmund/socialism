"""Document Coverage v1: deterministic controller, no Jev, no router."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.evaluate import evaluate_selection
from overgraph_ingest.coverage.select import document_scoped, global_top_k, progressive_unexamined
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.evaluate import judge_units
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite, load_retrieval_gold
from overgraph_ingest.retrieval.index import load_published_units
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import (
    SearchHit,
    encode_query,
    exhaustive_rank,
    rrf_fuse,
)


DEFAULT_GLOBAL_K = 50
DEFAULT_PER_DOCUMENT = (3, 5)
DEFAULT_SCORERS = ("hybrid", "dense")


@dataclass
class CoverageReport:
    payload: dict[str, object]


def run_coverage(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    global_k: int = DEFAULT_GLOBAL_K,
    per_document: tuple[int, ...] = DEFAULT_PER_DOCUMENT,
    scorers: tuple[str, ...] = DEFAULT_SCORERS,
) -> CoverageReport:
    golds = _golds(config.gold_path, gold_dir)
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    started = time.perf_counter()
    db = open_database(config.db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        units = load_published_units(writer)
        if any(unit.dense is None or unit.sparse is None for unit in units):
            raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
        sparse.fit([unit.text for unit in units])
        documents: list[dict[str, object]] = []
        for gold in golds:
            gold_started = time.perf_counter()
            dense_query, sparse_query = encode_query(gold.query, dense=dense, sparse=sparse)
            relevant, _negatives, absent = judge_units(units, gold)
            scorer_payloads: dict[str, object] = {}
            for mode in scorers:
                ranked = _ranked_hits(units, mode, dense_query, sparse_query)
                scorer_payloads[mode] = _strategies(
                    ranked,
                    units=units,
                    gold=gold,
                    relevant_keys=relevant,
                    global_k=global_k,
                    per_document=per_document,
                )
            documents.append(
                {
                    "gold_id": gold.id,
                    "query": gold.query,
                    "kind": gold.kind,
                    "relevant_units_in_graph": len(relevant),
                    "relevant_documents": gold.relevant_documents,
                    "absent_from_graph": [item.__dict__ for item in absent],
                    "wall_seconds": time.perf_counter() - gold_started,
                    "scorers": scorer_payloads,
                }
            )
        payload = {
            "operation": "coverage",
            "classify_unchanged": True,
            "controller": "deterministic_v1",
            "verified_absent_requires_all_units": True,
            "global_k": global_k,
            "per_document": list(per_document),
            "units": len(units),
            "documents_in_graph": len({unit.relative_path for unit in units}),
            "dense_model": dense.model,
            "golds": documents,
            "wall_seconds": time.perf_counter() - started,
        }
    finally:
        db.close()
    return CoverageReport(payload=payload)


def _strategies(
    ranked: list[SearchHit],
    *,
    units,
    gold: RetrievalGold,
    relevant_keys: set[str],
    global_k: int,
    per_document: tuple[int, ...],
) -> dict[str, object]:
    strategies: dict[str, object] = {
        "global_top_k": evaluate_selection(
            name="global_top_k",
            selected=global_top_k(ranked, global_k),
            units=units,
            gold=gold,
            relevant_keys=relevant_keys,
            extra_units=0,
            phase1_units=global_k,
        )
    }
    for n in per_document:
        scoped = document_scoped(ranked, n)
        strategies[f"document_scoped_{n}"] = evaluate_selection(
            name=f"document_scoped_{n}",
            selected=scoped,
            units=units,
            gold=gold,
            relevant_keys=relevant_keys,
            extra_units=len(scoped),
        )
        first, extra = progressive_unexamined(
            ranked,
            global_k=global_k,
            per_document=n,
        )
        strategies[f"progressive_unexamined_{n}"] = evaluate_selection(
            name=f"progressive_unexamined_{n}",
            selected=first + extra,
            units=units,
            gold=gold,
            relevant_keys=relevant_keys,
            extra_units=len(extra),
            phase1_units=len(first),
        )
    return strategies


def _ranked_hits(
    units: list,
    mode: str,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
) -> list[SearchHit]:
    if mode == "hybrid":
        dense_hits = exhaustive_rank(
            units, mode="dense", dense_query=dense_query, sparse_query=sparse_query
        )
        sparse_hits = exhaustive_rank(
            units, mode="sparse", dense_query=dense_query, sparse_query=sparse_query
        )
        return rrf_fuse([dense_hits, sparse_hits])
    return exhaustive_rank(
        units,
        mode=mode,
        dense_query=dense_query,
        sparse_query=sparse_query,
    )


def _golds(gold_path: Path | None, gold_dir: Path | None) -> list[RetrievalGold]:
    if gold_dir is not None:
        return load_gold_suite(gold_dir)
    if gold_path is None:
        raise ValueError("--retrieve-gold or --gold-dir is required for coverage")
    return [load_retrieval_gold(gold_path)]
