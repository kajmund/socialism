"""Coverage v2: classify C@8, then deepen touched or fairly, plus measured hops."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.coverage.cache import CachedAnswer, load_gold_cache
from overgraph_ingest.coverage.controller import FAIR, TOUCHED, metrics_payload, run_controller
from overgraph_ingest.coverage.run import _golds, _ranked_hits
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.jev.questions import CLASSIFY_QUESTION
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query

DEFAULT_CACHE = {
    "auto-renewal": Path("baselines/phase2-jev-classify-c8.json"),
    "notice-period": Path("data/jev-notice-period-C8.json"),
    "liability-cap": Path("data/jev-liability-cap-C8.json"),
    "confidentiality": Path("data/jev-confidentiality-C8.json"),
    "liability-secrecy-carveout": Path("data/jev-liability-secrecy-carveout-C8.json"),
}


@dataclass
class CoverageV2Report:
    payload: dict[str, object]


def run_coverage_v2(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    client: JevClient | None = None,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-1.13.0",
    timeout_seconds: float = 8.0,
    concurrency: int = 8,
    global_k: int = 50,
    max_passes: int = 3,
    variants: tuple[str, ...] = (TOUCHED, FAIR),
    cache_root: Path | None = None,
    scorer: str = "hybrid",
) -> CoverageV2Report:
    golds = _golds(config.gold_path, gold_dir)
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    jev = client or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    started = time.perf_counter()
    db = open_database(config.db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        context = load_graph_context(writer)
        if any(unit.dense is None or unit.sparse is None for unit in context.units):
            raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
        sparse.fit([unit.text for unit in context.units])
        gold_rows: list[dict[str, object]] = []
        for gold in golds:
            gold_started = time.perf_counter()
            dense_query, sparse_query = encode_query(gold.query, dense=dense, sparse=sparse)
            ranked = _ranked_hits(context.units, scorer, dense_query, sparse_query)
            cache = _cache_for(gold.id, cache_root)
            question = gold.classify_question or CLASSIFY_QUESTION
            variant_rows: dict[str, object] = {}
            for variant in variants:
                result = run_controller(
                    variant=variant,
                    ranked=ranked,
                    context=context,
                    gold=gold,
                    client=jev,
                    cache=cache,
                    question=question,
                    model=jev_model,
                    timeout_seconds=timeout_seconds,
                    concurrency=concurrency,
                    global_k=global_k,
                    max_passes=max_passes,
                )
                for judged in result.judgments:
                    cache.setdefault(
                        judged.key,
                        CachedAnswer(judged.predicted, judged.confidence, "v2-live"),
                    )
                result.wall_seconds = time.perf_counter() - gold_started
                payload = metrics_payload(result, gold)
                payload["wall_seconds"] = result.wall_seconds
                variant_rows[variant] = payload
            gold_rows.append(
                {
                    "gold_id": gold.id,
                    "query": gold.query,
                    "proof_kind": gold.proof_kind,
                    "relevant_documents": gold.relevant_documents,
                    "variants": variant_rows,
                }
            )
        payload = {
            "operation": "coverage",
            "controller": "deterministic_v2",
            "classify_unchanged": True,
            "verified_absent_requires_all_units": True,
            "scorer": scorer,
            "global_k": global_k,
            "max_passes": max_passes,
            "jev_model": jev_model,
            "concurrency": concurrency,
            "golds": gold_rows,
            "wall_seconds": time.perf_counter() - started,
        }
    finally:
        db.close()
    return CoverageV2Report(payload=payload)


def _cache_for(gold_id: str, cache_root: Path | None) -> dict[str, CachedAnswer]:
    relative = DEFAULT_CACHE.get(gold_id)
    if relative is None:
        return {}
    root = cache_root if cache_root is not None else Path(__file__).resolve().parents[2]
    path = root / relative
    if not path.is_file():
        return {}
    return load_gold_cache(path, source=str(relative))
