"""Isolate retrieval latency: engine search vs Python ranking vs hydration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from statistics import mean
from typing import Any

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.graph.schema import TEXT_UNIT
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder, cosine, sparse_dot
from overgraph_ingest.retrieval.gold import load_retrieval_gold
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query, exhaustive_rank, rrf_fuse, search_units


DEFAULT_QUERY = "Vilka avtal innehåller en sekretessplikt?"
DEFAULT_REPEATS = 5
DEFAULT_K = 50


@dataclass
class ProfileReport:
    payload: dict[str, object]


def run_retrieval_profile(
    config: RetrievalConfig,
    *,
    query: str | None = None,
    repeats: int = DEFAULT_REPEATS,
    k: int = DEFAULT_K,
) -> ProfileReport:
    text = query or _query_from_gold(config) or DEFAULT_QUERY
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    db = open_database(config.db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        load_started = time.perf_counter()
        units = load_published_units(writer)
        load_seconds = time.perf_counter() - load_started
        if any(unit.dense is None or unit.sparse is None for unit in units):
            raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
        sparse.fit([unit.text for unit in units])
        encode_started = time.perf_counter()
        dense_query, sparse_query = encode_query(text, dense=dense, sparse=sparse)
        first_encode_seconds = time.perf_counter() - encode_started
        encode_repeats = _repeat(
            repeats,
            lambda: encode_query(text, dense=dense, sparse=sparse),
        )
        python = profile_python(units, dense_query, sparse_query, repeats=repeats)
        engine = profile_engine(
            db,
            units,
            dense_query=dense_query,
            sparse_query=sparse_query,
            k=k,
            fusion_mode=config.fusion_mode,
            repeats=repeats,
        )
        payload = {
            "operation": "retrieval_profile",
            "experiment": "retrieval_latency_v1",
            "previous_dense_sparse_seconds_were_python_exhaustive": True,
            "dense_and_sparse_run_sequentially": True,
            "do_not_optimize_engine": True,
            "query": text,
            "k": k,
            "repeats": repeats,
            "units": len(units),
            "dense_model": dense.model,
            "dense_dimension": dense.dimension,
            "sparse_encoder": sparse.encoder_id,
            "corpus": _corpus_stats(units),
            "first_encode_seconds": first_encode_seconds,
            "stages": {
                "load_published_units": {"seconds": load_seconds},
                "encode_query": encode_repeats,
                **python,
                **engine,
            },
            "headline": _headline(python, engine, encode_repeats),
        }
    finally:
        db.close()
    return ProfileReport(payload=payload)


def profile_python(
    units: list[StoredUnit],
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    *,
    repeats: int = DEFAULT_REPEATS,
) -> dict[str, object]:
    dense_score = _repeat(repeats, lambda: _score_only(units, "dense", dense_query, sparse_query))
    sparse_score = _repeat(repeats, lambda: _score_only(units, "sparse", dense_query, sparse_query))
    dense_rank = _repeat(
        repeats,
        lambda: exhaustive_rank(
            units, mode="dense", dense_query=dense_query, sparse_query=sparse_query
        ),
    )
    sparse_rank = _repeat(
        repeats,
        lambda: exhaustive_rank(
            units, mode="sparse", dense_query=dense_query, sparse_query=sparse_query
        ),
    )
    dense_hits = exhaustive_rank(
        units, mode="dense", dense_query=dense_query, sparse_query=sparse_query
    )
    sparse_hits = exhaustive_rank(
        units, mode="sparse", dense_query=dense_query, sparse_query=sparse_query
    )
    fusion = _repeat(repeats, lambda: rrf_fuse([dense_hits, sparse_hits]))
    sequential = {
        "mean_seconds": dense_rank["mean_seconds"] + sparse_rank["mean_seconds"] + fusion["mean_seconds"],
        "note": "dense then sparse then fusion, as in query-expansion timing",
    }
    return {
        "python_dense_score": dense_score,
        "python_sparse_score": sparse_score,
        "python_dense_rank": dense_rank,
        "python_sparse_rank": sparse_rank,
        "python_fusion": fusion,
        "python_dense_then_sparse": sequential,
    }


def profile_engine(
    db: Any,
    units: list[StoredUnit],
    *,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    k: int,
    fusion_mode: str,
    repeats: int = DEFAULT_REPEATS,
) -> dict[str, object]:
    label_filter = {"labels": [TEXT_UNIT], "mode": "all"}
    dense_raw = _repeat(
        repeats,
        lambda: db.vector_search(
            "dense", k, dense_query=dense_query, label_filter=label_filter
        ),
    )
    sparse_raw = _repeat(
        repeats,
        lambda: db.vector_search(
            "sparse", k, sparse_query=sparse_query, label_filter=label_filter
        ),
    )
    hybrid_raw = _repeat(
        repeats,
        lambda: db.vector_search(
            "hybrid",
            k,
            dense_query=dense_query,
            sparse_query=sparse_query,
            label_filter=label_filter,
            fusion_mode=fusion_mode,
        ),
    )
    hydrate = _repeat(
        repeats,
        lambda: search_units(
            db,
            units,
            mode="hybrid",
            k=k,
            dense_query=dense_query,
            sparse_query=sparse_query,
            fusion_mode=fusion_mode,
        ),
    )
    return {
        "engine_dense": dense_raw,
        "engine_sparse": sparse_raw,
        "engine_hybrid": hybrid_raw,
        "engine_hybrid_plus_hydrate": hydrate,
        "engine_dense_then_sparse": {
            "mean_seconds": dense_raw["mean_seconds"] + sparse_raw["mean_seconds"],
            "note": "sequential calls; hybrid is a separate engine path",
        },
        "hydrate_overhead_seconds": hydrate["mean_seconds"] - hybrid_raw["mean_seconds"],
    }


def _score_only(
    units: list[StoredUnit],
    mode: str,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
) -> list[float]:
    scores: list[float] = []
    for unit in units:
        if mode == "dense":
            if unit.dense is None:
                scores.append(0.0)
            else:
                scores.append(cosine(dense_query, unit.dense))
        elif unit.sparse is None:
            scores.append(0.0)
        else:
            scores.append(sparse_dot(sparse_query, unit.sparse))
    return scores


def _repeat(repeats: int, work) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    work()
    samples: list[float] = []
    last = None
    for _ in range(repeats):
        started = time.perf_counter()
        last = work()
        samples.append(time.perf_counter() - started)
    return {
        "repeats": repeats,
        "mean_seconds": mean(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "samples": samples,
        "result_count": _result_count(last),
    }


def _result_count(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return len(value)
    return None


def _corpus_stats(units: list[StoredUnit]) -> dict[str, object]:
    sparse_nnz = [len(unit.sparse or ()) for unit in units]
    return {
        "units": len(units),
        "dense_dimension": len(units[0].dense or ()) if units else 0,
        "mean_sparse_nnz": mean(sparse_nnz) if sparse_nnz else 0.0,
        "max_sparse_nnz": max(sparse_nnz) if sparse_nnz else 0,
        "python_dense_muladds": len(units) * len(units[0].dense or ()) if units else 0,
    }


def _headline(python: dict[str, object], engine: dict[str, object], encode: dict[str, object]) -> dict[str, object]:
    return {
        "encode_mean_seconds": encode["mean_seconds"],
        "python_dense_rank_mean_seconds": python["python_dense_rank"]["mean_seconds"],
        "python_sparse_rank_mean_seconds": python["python_sparse_rank"]["mean_seconds"],
        "engine_dense_mean_seconds": engine["engine_dense"]["mean_seconds"],
        "engine_sparse_mean_seconds": engine["engine_sparse"]["mean_seconds"],
        "engine_hybrid_mean_seconds": engine["engine_hybrid"]["mean_seconds"],
        "hydrate_overhead_seconds": engine["hydrate_overhead_seconds"],
        "python_dense_then_sparse_mean_seconds": python["python_dense_then_sparse"]["mean_seconds"],
        "engine_dense_then_sparse_mean_seconds": engine["engine_dense_then_sparse"]["mean_seconds"],
    }


def _query_from_gold(config: RetrievalConfig) -> str | None:
    if config.gold_path is None:
        return None
    return load_retrieval_gold(config.gold_path).query
