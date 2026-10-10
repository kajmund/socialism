"""Run embedding + retrieval quality for one gold query."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.retrieval.encode import (
    DENSE_DIMENSION,
    DENSE_MODEL,
    HashedDenseEncoder,
    LexicalSparseEncoder,
    OpenAIDenseEncoder,
)
from overgraph_ingest.retrieval.evaluate import (
    evaluate_strategy,
    judge_units,
    metrics_payload,
    ranking_quality,
)
from overgraph_ingest.retrieval.gold import RetrievalGold, load_retrieval_gold
from overgraph_ingest.retrieval.index import embed_published_units, load_published_units
from overgraph_ingest.retrieval.search import (
    SearchHit,
    encode_query,
    exhaustive_rank,
    rrf_fuse,
    search_units,
    union_pool,
)


MODES = ("dense", "sparse", "hybrid")
UNION_RRF = "union_rrf"
UNION_POOL = "union_pool"


@dataclass
class RetrievalReport:
    payload: dict[str, object]


def run_retrieval(config: RetrievalConfig) -> RetrievalReport:
    if config.gold_path is None:
        raise ValueError("--retrieve-gold is required")
    gold = load_retrieval_gold(config.gold_path)
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    db = open_database(config.db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        index_stats = None
        if config.embed:
            index_stats = embed_published_units(writer, dense=dense, sparse=sparse)
        units = load_published_units(writer)
        if any(unit.dense is None or unit.sparse is None for unit in units):
            raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
        sparse.fit([unit.text for unit in units])
        dense_query, sparse_query = encode_query(gold.query, dense=dense, sparse=sparse)
        relevant, negatives, absent = judge_units(units, gold)
        max_k = max(config.ks)
        engine_hits: dict[str, list[SearchHit]] = {}
        strategies: dict[str, object] = {}
        for mode in MODES:
            hits = search_units(
                db,
                units,
                mode=mode,
                k=max_k,
                dense_query=dense_query,
                sparse_query=sparse_query,
                fusion_mode=config.fusion_mode,
            )
            engine_hits[mode] = hits
            exhaustive = exhaustive_rank(
                units,
                mode=mode,
                dense_query=dense_query,
                sparse_query=sparse_query,
            )
            strategies[mode] = {
                "ranking": ranking_quality(hits, gold, relevant, negatives),
                "at_k": {
                    str(k): metrics_payload(
                        evaluate_strategy(
                            mode=mode,
                            k=k,
                            gold=gold,
                            hits=hits,
                            exhaustive=exhaustive,
                            relevant_keys=relevant,
                            negative_keys=negatives,
                            absent=absent,
                        )
                    )
                    for k in config.ks
                }
            }
        fused = rrf_fuse([engine_hits["dense"], engine_hits["hybrid"]], k=max_k)
        strategies[UNION_RRF] = {
            "ranking": ranking_quality(fused, gold, relevant, negatives),
            "at_k": {
                str(k): metrics_payload(
                    evaluate_strategy(
                        mode=UNION_RRF,
                        k=k,
                        gold=gold,
                        hits=fused,
                        exhaustive=fused,
                        relevant_keys=relevant,
                        negative_keys=negatives,
                        absent=absent,
                    )
                )
                for k in config.ks
            },
        }
        strategies[UNION_POOL] = {
            "at_k": {
                str(k): _pool_metrics(
                    k=k,
                    gold=gold,
                    dense=engine_hits["dense"],
                    hybrid=engine_hits["hybrid"],
                    relevant_keys=relevant,
                    negative_keys=negatives,
                    absent=absent,
                )
                for k in config.ks
            }
        }
        payload = {
            "gold_id": gold.id,
            "query": gold.query,
            "notes": gold.notes,
            "dense_model": dense.model,
            "dense_dimension": dense.dimension,
            "sparse_encoder": sparse.encoder_id,
            "fusion_mode": config.fusion_mode,
            "units": len(units),
            "relevant_units_in_graph": len(relevant),
            "relevant_documents": gold.relevant_documents,
            "passage_documents": gold.passage_documents,
            "hard_negatives_in_graph": len(negatives),
            "absent_from_graph": [item.__dict__ for item in absent],
            "embedded": None if index_stats is None else index_stats.embedded,
            "strategies": strategies,
        }
    finally:
        db.close()
    return RetrievalReport(payload=payload)


def _pool_metrics(
    *,
    k: int,
    gold: RetrievalGold,
    dense: list[SearchHit],
    hybrid: list[SearchHit],
    relevant_keys: set[str],
    negative_keys: set[str],
    absent,
) -> dict[str, object]:
    dense_top = [hit for hit in dense if hit.rank <= k]
    hybrid_top = [hit for hit in hybrid if hit.rank <= k]
    dense_keys = {hit.key for hit in dense_top}
    hybrid_keys = {hit.key for hit in hybrid_top}
    pool = union_pool([dense, hybrid], per_list=k)
    payload = metrics_payload(
        evaluate_strategy(
            mode=UNION_POOL,
            k=len(pool),
            gold=gold,
            hits=pool,
            exhaustive=pool,
            relevant_keys=relevant_keys,
            negative_keys=negative_keys,
            absent=absent,
        )
    )
    payload["source_k"] = k
    payload["pool_size"] = len(pool)
    payload["dense_in_pool"] = len(dense_keys)
    payload["hybrid_in_pool"] = len(hybrid_keys)
    payload["overlap"] = len(dense_keys & hybrid_keys)
    return payload


def _dense_encoder(config: RetrievalConfig, dimension: int):
    if config.dense_model == "hashed-dense-v1":
        return HashedDenseEncoder(dimension)
    if config.openai_api_key is None:
        if dimension == DENSE_DIMENSION and config.dense_model == DENSE_MODEL:
            raise ValueError("--openai-api-key is required for text-embedding-3-large")
        return HashedDenseEncoder(dimension)
    return OpenAIDenseEncoder(
        api_key=config.openai_api_key,
        model=config.dense_model,
        dimension=dimension,
        base_url=config.openai_base_url,
    )
