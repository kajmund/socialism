"""Compare embedding pairs. Same retriever, same golds, separate databases."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.config import IngestConfig, RetrievalConfig
from overgraph_ingest.coverage.run import _golds
from overgraph_ingest.graph.schema import TEXT_UNIT
from overgraph_ingest.graph.writer import (
    GraphWriter,
    open_database,
    read_manifest_dimension,
    resolve_dimension,
)
from overgraph_ingest.pipeline import _peak_rss_bytes, run_ingest
from overgraph_ingest.retrieval.bge_m3 import BGE_M3_DENSE_DIMENSION, BGE_M3_MODEL, bge_m3_load_seconds
from overgraph_ingest.retrieval.encode import (
    DENSE_DIMENSION,
    DENSE_MODEL,
    SPARSE_ENCODER_ID,
    build_dense_encoder,
    build_sparse_encoder,
)
from overgraph_ingest.retrieval.evaluate import evaluate_strategy, judge_units, metrics_payload
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import encode_unit_vectors, load_published_units
from overgraph_ingest.retrieval.search import encode_query, search_units
from overgraph_ingest.retrieval.stages import PIPELINE_STAGES

REFERENCE_VARIANT = "openai-tfidf"
REFERENCE_DIMENSION = DENSE_DIMENSION
CANDIDATE_K = 50
REPORT_KS = (20, 50)
MODES = ("dense", "sparse", "hybrid")


@dataclass(frozen=True)
class EmbeddingVariant:
    id: str
    dense_model: str
    sparse_encoder: str
    dimension: int
    write_dense: bool
    write_sparse: bool
    reuse_reference: bool
    copy_reference: bool
    db_name: str


VARIANTS = (
    EmbeddingVariant(
        REFERENCE_VARIANT,
        DENSE_MODEL,
        SPARSE_ENCODER_ID,
        REFERENCE_DIMENSION,
        False,
        False,
        True,
        False,
        "",
    ),
    EmbeddingVariant(
        "bge-m3-tfidf",
        BGE_M3_MODEL,
        SPARSE_ENCODER_ID,
        BGE_M3_DENSE_DIMENSION,
        True,
        True,
        False,
        False,
        "extra-overgraph-bge-m3-tfidf",
    ),
    EmbeddingVariant(
        "bge-m3",
        BGE_M3_MODEL,
        "bge-m3-sparse-v1",
        BGE_M3_DENSE_DIMENSION,
        True,
        True,
        False,
        False,
        "extra-overgraph-bge-m3",
    ),
    EmbeddingVariant(
        "openai-bge-sparse",
        DENSE_MODEL,
        "bge-m3-sparse-v1",
        REFERENCE_DIMENSION,
        False,
        True,
        False,
        True,
        "extra-overgraph-openai-bge-sparse",
    ),
)


@dataclass
class EmbeddingCompareReport:
    payload: dict[str, object]


def run_embedding_compare(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    input_dir: Path | None = None,
    cache_dir: Path | None = None,
    collection_id: str = "extra-corpus",
    query_repeats: int = 3,
) -> EmbeddingCompareReport:
    reference = config.db_path
    existing = read_manifest_dimension(reference)
    if existing != REFERENCE_DIMENSION:
        raise ValueError(
            f"reference database {reference} must be dense dimension {REFERENCE_DIMENSION}"
        )
    golds = _golds(config.gold_path, gold_dir, include_held_out=False)
    started = time.perf_counter()
    rows = []
    for variant in VARIANTS:
        rows.append(
            _run_variant(
                variant,
                config=config,
                golds=golds,
                input_dir=input_dir,
                cache_dir=cache_dir,
                collection_id=collection_id,
                query_repeats=query_repeats,
            )
        )
    return EmbeddingCompareReport(
        payload={
            "operation": "retrieval",
            "experiment": "embedding_models_v1",
            "pipeline_stages": list(PIPELINE_STAGES),
            "default_retriever_unchanged": True,
            "does_not_replace_c8": True,
            "does_not_replace_coverage_v3": True,
            "candidate_k": CANDIDATE_K,
            "ks": list(REPORT_KS),
            "reference_db": str(reference),
            "golds": [gold.id for gold in golds],
            "variants": rows,
            "peak_rss_mb": _peak_rss_bytes() / (1024 * 1024),
            "wall_seconds": time.perf_counter() - started,
        }
    )


def _run_variant(
    variant: EmbeddingVariant,
    *,
    config: RetrievalConfig,
    golds: list[RetrievalGold],
    input_dir: Path | None,
    cache_dir: Path | None,
    collection_id: str,
    query_repeats: int,
) -> dict[str, object]:
    db_path, prepared = _prepare_database(
        variant,
        reference=config.db_path,
        input_dir=input_dir,
        cache_dir=cache_dir,
        collection_id=collection_id,
        write_batch_size=config.write_batch_size,
    )
    dense = build_dense_encoder(
        model=variant.dense_model,
        dimension=variant.dimension,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
    )
    sparse = build_sparse_encoder(variant.sparse_encoder)
    dimension = resolve_dimension(db_path, variant.dimension)
    # The database stays open only around local database work. Encoder calls
    # (OpenAI, BGE-M3, sparse.fit) always run with the handle closed.
    db = open_database(db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        units = load_published_units(writer)
        write_dense, write_sparse = _write_flags(variant, writer, units, prepared)
    finally:
        db.close()
    embed_stats = None
    embed_seconds = None
    if write_dense or write_sparse:
        embed_started = time.perf_counter()
        embed_stats, payloads = encode_unit_vectors(
            units,
            dense=dense,
            sparse=sparse,
            write_dense=write_dense,
            write_sparse=write_sparse,
        )
        embed_seconds = time.perf_counter() - embed_started
        db = open_database(db_path, dimension)
        try:
            writer = GraphWriter(db, batch_size=config.write_batch_size)
            writer.write_vectors(payloads)
            writer.db.flush()
            units = load_published_units(writer)
        finally:
            db.close()
    if any(unit.dense is None or unit.sparse is None for unit in units):
        raise RuntimeError(f"{variant.id}: TextUnits are missing vectors")
    sparse.fit([unit.text for unit in units])
    gold_rows = []
    query_samples: list[float] = []
    search_samples: list[float] = []
    for index, gold in enumerate(golds):
        encode_started = time.perf_counter()
        dense_query, sparse_query = encode_query(gold.query, dense=dense, sparse=sparse)
        encode_seconds = time.perf_counter() - encode_started
        if index > 0:
            query_samples.append(encode_seconds)
        db = open_database(db_path, dimension)
        try:
            search_started = time.perf_counter()
            hits = {
                mode: search_units(
                    db,
                    units,
                    mode=mode,
                    k=CANDIDATE_K,
                    dense_query=dense_query,
                    sparse_query=sparse_query,
                    fusion_mode=config.fusion_mode,
                )
                for mode in MODES
            }
            search_seconds = time.perf_counter() - search_started
        finally:
            db.close()
        search_samples.append(search_seconds)
        relevant, negatives, absent = judge_units(units, gold)
        gold_rows.append(
            {
                "gold_id": gold.id,
                "relevant_units": len(relevant),
                "relevant_documents": gold.relevant_documents,
                "encode_seconds": encode_seconds,
                "engine_search_seconds": search_seconds,
                "absent_from_graph": [item.__dict__ for item in absent],
                "modes": {
                    mode: _mode_metrics(
                        hits[mode],
                        gold=gold,
                        relevant=relevant,
                        negatives=negatives,
                        absent=absent,
                    )
                    for mode in MODES
                },
            }
        )
        if index == 0 and query_repeats > 0:
            for _ in range(query_repeats):
                repeat_started = time.perf_counter()
                encode_query(gold.query, dense=dense, sparse=sparse)
                query_samples.append(time.perf_counter() - repeat_started)
    first_encode = gold_rows[0]["encode_seconds"] if gold_rows else None
    return {
        "id": variant.id,
        "db": str(db_path),
        "dense_model": variant.dense_model,
        "sparse_encoder": variant.sparse_encoder,
        "dense_dimension": variant.dimension,
        "wrote_reference": False,
        "embedded": None if embed_stats is None else embed_stats.embedded,
        "embed_seconds": embed_seconds,
        "bge_m3_load_seconds": bge_m3_load_seconds(),
        "units": len(units),
        "cold_query_seconds": first_encode,
        "warm_query_seconds": _mean(query_samples),
        "engine_search_seconds": _mean(search_samples),
        "peak_rss_mb": _peak_rss_bytes() / (1024 * 1024),
        "golds": gold_rows,
    }


def _mode_metrics(hits, *, gold, relevant, negatives, absent) -> dict[str, object]:
    rows = {}
    for k in REPORT_KS:
        metrics = metrics_payload(
            evaluate_strategy(
                mode="compare",
                k=k,
                gold=gold,
                hits=hits,
                exhaustive=hits,
                relevant_keys=relevant,
                negative_keys=negatives,
                absent=absent,
            )
        )
        rows[str(k)] = {
            "recall": metrics.get("recall"),
            "document_coverage": metrics.get("document_coverage"),
            "documents_found": metrics.get("documents_found"),
            "hard_negatives_in_topk": metrics.get("hard_negatives_in_topk"),
            "hard_negative_ranks": metrics.get("hard_negative_ranks"),
            "mrr": metrics.get("mrr"),
            "first_relevant_rank": metrics.get("first_relevant_rank"),
        }
    return rows


def _prepare_database(
    variant: EmbeddingVariant,
    *,
    reference: Path,
    input_dir: Path | None,
    cache_dir: Path | None,
    collection_id: str,
    write_batch_size: int,
) -> tuple[Path, str]:
    if variant.reuse_reference:
        return reference, "reuse"
    dest = reference.parent / variant.db_name
    if dest.exists():
        existing = read_manifest_dimension(dest)
        if existing != variant.dimension:
            raise ValueError(
                f"{dest} is locked to dense dimension {existing}, variant {variant.id} "
                f"needs {variant.dimension}"
            )
        return dest, "existing"
    if variant.copy_reference:
        shutil.copytree(reference, dest)
        return dest, "copy"
    if input_dir is None or cache_dir is None:
        raise ValueError("--input and --cache-dir are required to create embedding-compare databases")
    run_ingest(
        IngestConfig(
            db_path=dest,
            input_dir=input_dir,
            cache_dir=cache_dir,
            collection_id=collection_id,
            dense_dimension=variant.dimension,
            write_batch_size=write_batch_size,
        )
    )
    return dest, "ingest"


def _write_flags(
    variant: EmbeddingVariant,
    writer: GraphWriter,
    units,
    prepared: str,
) -> tuple[bool, bool]:
    if variant.reuse_reference or prepared == "reuse":
        return False, False
    stored_dense, stored_sparse = _stored_encoders(writer, units)
    missing = any(unit.dense is None or unit.sparse is None for unit in units)
    if (
        not missing
        and stored_dense == variant.dense_model
        and stored_sparse == variant.sparse_encoder
    ):
        return False, False
    if prepared == "copy" or (
        stored_dense == variant.dense_model and stored_sparse != variant.sparse_encoder
    ):
        return False, True
    if missing:
        return variant.write_dense, variant.write_sparse
    raise RuntimeError(
        f"{variant.id} database has dense={stored_dense!r} sparse={stored_sparse!r}, "
        f"expected {variant.dense_model} / {variant.sparse_encoder}"
    )


def _stored_encoders(writer: GraphWriter, units) -> tuple[str | None, str | None]:
    if not units:
        return None, None
    view = writer.get_node(TEXT_UNIT, units[0].key)
    if view is None:
        return None, None
    props = dict(view.props)
    dense = props.get("dense_model")
    sparse = props.get("sparse_encoder")
    return (str(dense) if dense else None, str(sparse) if sparse else None)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
