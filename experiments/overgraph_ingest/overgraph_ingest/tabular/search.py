"""Document-local hybrid ranking. Does not call OverGraph vector_search."""

from __future__ import annotations

from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit, exhaustive_rank, rrf_fuse

RECALL_KS = (3, 5, 10)
DEFAULT_K = 5
STRATEGIES = ("dense", "sparse", "hybrid")


def document_units(units: list[StoredUnit], relative_path: str) -> list[StoredUnit]:
    return [unit for unit in units if unit.relative_path == relative_path]


def document_local_ranks(
    units: list[StoredUnit],
    relative_path: str,
    *,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
) -> dict[str, list[SearchHit]]:
    local = document_units(units, relative_path)
    if not local:
        return {name: [] for name in STRATEGIES}
    if any(unit.relative_path != relative_path for unit in local):
        raise ValueError("document filter leaked another path")
    dense = exhaustive_rank(
        local, mode="dense", dense_query=dense_query, sparse_query=sparse_query
    )
    sparse = exhaustive_rank(
        local, mode="sparse", dense_query=dense_query, sparse_query=sparse_query
    )
    hybrid = rrf_fuse([dense, sparse])
    ranked = {"dense": dense, "sparse": sparse, "hybrid": hybrid}
    if any(hit.relative_path != relative_path for hits in ranked.values() for hit in hits):
        raise ValueError("document-local rank leaked another path")
    return ranked


def document_local_rank(
    units: list[StoredUnit],
    relative_path: str,
    *,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
) -> list[SearchHit]:
    return document_local_ranks(
        units,
        relative_path,
        dense_query=dense_query,
        sparse_query=sparse_query,
    )["hybrid"]


def recall_at(
    ranked: list[SearchHit],
    relevant_keys: set[str],
    ks: tuple[int, ...] = RECALL_KS,
) -> dict[str, float]:
    payload: dict[str, float] = {}
    for k in ks:
        keys = {hit.key for hit in ranked[:k]}
        payload[f"recall@{k}"] = (
            (len(keys & relevant_keys) / len(relevant_keys)) if relevant_keys else 0.0
        )
    return payload
