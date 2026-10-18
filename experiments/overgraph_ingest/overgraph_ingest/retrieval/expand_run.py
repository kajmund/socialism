"""Compare baseline vs appended vs fused query expansion. Retrieval only."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.evaluate import coverage_curve
from overgraph_ingest.coverage.run import _golds
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.evaluate import evaluate_strategy, judge_units, metrics_payload
from overgraph_ingest.retrieval.expand import (
    APPEND,
    BASELINE,
    EXPANSION_POLICY,
    FUSE,
    expansion_for,
    load_expansions,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import load_published_units
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import SearchHit, encode_query, exhaustive_rank, rrf_fuse

MODES = ("dense", "sparse", "hybrid")
DEFAULT_KS = (5, 10, 20, 50, 100)


@dataclass
class ExpansionReport:
    payload: dict[str, object]


def run_query_expansion(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    expansions_path: Path | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> ExpansionReport:
    golds = _golds(config.gold_path, gold_dir, include_held_out=True)
    expansions = load_expansions(expansions_path)
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
        gold_rows = []
        for gold in golds:
            expansion = expansion_for(gold, expansions)
            relevant, negatives, absent = judge_units(units, gold)
            queries = {
                BASELINE: gold.query,
                APPEND: expansion.append(gold.query),
            }
            timed = {
                name: _timed_rankings(text, units=units, dense=dense, sparse=sparse)
                for name, text in queries.items()
            }
            rankings = {name: timed[name]["rankings"] for name in queries}
            fuse_started = time.perf_counter()
            rankings[FUSE] = {
                mode: rrf_fuse([rankings[BASELINE][mode], rankings[APPEND][mode]])
                for mode in MODES
            }
            fuse_seconds = time.perf_counter() - fuse_started
            variants = {}
            for name, ranked in rankings.items():
                variants[name] = {
                    "query": queries.get(name, queries[APPEND] if name == FUSE else gold.query),
                    "modes": {
                        mode: _mode_metrics(
                            ranked[mode],
                            gold=gold,
                            relevant=relevant,
                            negatives=negatives,
                            absent=absent,
                            ks=ks,
                        )
                        for mode in MODES
                    },
                }
            gold_rows.append(
                {
                    "gold_id": gold.id,
                    "query": gold.query,
                    "concept": expansion.concept,
                    "terms": list(expansion.terms),
                    "expanded_query": queries[APPEND],
                    "relevant_units": len(relevant),
                    "relevant_documents": gold.relevant_documents,
                    "absent_from_graph": [item.__dict__ for item in absent],
                    "split": gold.split,
                    "latency": {
                        BASELINE: timed[BASELINE]["latency"],
                        APPEND: timed[APPEND]["latency"],
                        FUSE: {
                            "fusion_seconds": fuse_seconds,
                            "encode_seconds": None,
                            "dense_search_seconds": None,
                            "sparse_search_seconds": None,
                        },
                    },
                    "delta_at_50": _delta(variants),
                    "variants": variants,
                }
            )
        payload = {
            "operation": "retrieval",
            "experiment": "query_expansion_v2_generalization",
            "classify_unchanged": True,
            "expansion": "deterministic_lexicon",
            "default_retriever_unchanged": True,
            "expansion_policy": dict(EXPANSION_POLICY),
            "dense_model": dense.model,
            "ks": list(ks),
            "golds": gold_rows,
            "wall_seconds": time.perf_counter() - started,
        }
    finally:
        db.close()
    return ExpansionReport(payload=payload)


def _timed_rankings(query: str, *, units, dense, sparse) -> dict[str, object]:
    encode_started = time.perf_counter()
    dense_query, sparse_query = encode_query(query, dense=dense, sparse=sparse)
    encode_seconds = time.perf_counter() - encode_started
    dense_started = time.perf_counter()
    dense_hits = exhaustive_rank(
        units, mode="dense", dense_query=dense_query, sparse_query=sparse_query
    )
    dense_seconds = time.perf_counter() - dense_started
    sparse_started = time.perf_counter()
    sparse_hits = exhaustive_rank(
        units, mode="sparse", dense_query=dense_query, sparse_query=sparse_query
    )
    sparse_seconds = time.perf_counter() - sparse_started
    hybrid_started = time.perf_counter()
    hybrid_hits = rrf_fuse([dense_hits, sparse_hits])
    hybrid_seconds = time.perf_counter() - hybrid_started
    return {
        "rankings": {
            "dense": dense_hits,
            "sparse": sparse_hits,
            "hybrid": hybrid_hits,
        },
        "latency": {
            "encode_seconds": encode_seconds,
            "dense_search_seconds": dense_seconds,
            "sparse_search_seconds": sparse_seconds,
            "fusion_seconds": hybrid_seconds,
            "ranking_seconds": dense_seconds + sparse_seconds + hybrid_seconds,
        },
    }


def _mode_metrics(
    ranked: list[SearchHit],
    *,
    gold: RetrievalGold,
    relevant: set[str],
    negatives: set[str],
    absent,
    ks: tuple[int, ...],
) -> dict[str, object]:
    curve = coverage_curve(ranked, gold, relevant)
    at_k = {
        str(k): metrics_payload(
            evaluate_strategy(
                mode="expand",
                k=k,
                gold=gold,
                hits=ranked,
                exhaustive=ranked,
                relevant_keys=relevant,
                negative_keys=negatives,
                absent=absent,
            )
        )
        for k in ks
    }
    at_50 = at_k.get("50") or {}
    return {
        "recall_at_50": at_50.get("recall"),
        "document_coverage_at_50": at_50.get("document_coverage"),
        "hard_negatives_at_50": at_50.get("hard_negatives_in_topk"),
        "units_to_document_recall": curve["units_to_document_recall"],
        "final_document_recall": curve["final_document_recall"],
        "at_k": {
            key: {
                "recall": row.get("recall"),
                "document_coverage": row.get("document_coverage"),
                "precision": row.get("precision"),
                "hard_negatives_in_topk": row.get("hard_negatives_in_topk"),
                "documents_found": row.get("documents_found"),
            }
            for key, row in at_k.items()
        },
    }


def _delta(variants: dict[str, object]) -> dict[str, object]:
    rows = {}
    baseline = variants[BASELINE]["modes"]
    for variant in (APPEND, FUSE):
        modes = {}
        for mode in MODES:
            base = baseline[mode]
            treat = variants[variant]["modes"][mode]
            modes[mode] = {
                "recall_at_50": _sub(treat["recall_at_50"], base["recall_at_50"]),
                "document_coverage_at_50": _sub(
                    treat["document_coverage_at_50"], base["document_coverage_at_50"]
                ),
                "units_to_full_document_recall": _int_sub(
                    treat["units_to_document_recall"].get("1.0"),
                    base["units_to_document_recall"].get("1.0"),
                ),
            }
        rows[variant] = modes
    return rows


def _sub(left, right) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _int_sub(left, right) -> int | None:
    if left is None or right is None:
        return None
    return int(left) - int(right)
