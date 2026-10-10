"""Dense, sparse, hybrid OverGraph search plus exhaustive in-process ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from overgraph_ingest.graph.schema import TEXT_UNIT
from overgraph_ingest.retrieval.encode import (
    DenseEncoder,
    LexicalSparseEncoder,
    cosine,
    sparse_dot,
)
from overgraph_ingest.retrieval.index import StoredUnit


@dataclass(frozen=True)
class SearchHit:
    node_id: int
    key: str
    score: float
    rank: int
    document_id: str
    relative_path: str
    text: str


def search_units(
    db: Any,
    units: list[StoredUnit],
    *,
    mode: str,
    k: int,
    dense_query: list[float] | None = None,
    sparse_query: list[tuple[int, float]] | None = None,
    fusion_mode: str = "reciprocal_rank",
) -> list[SearchHit]:
    kwargs: dict[str, object] = {
        "label_filter": {"labels": [TEXT_UNIT], "mode": "all"},
    }
    if dense_query is not None:
        kwargs["dense_query"] = dense_query
    if sparse_query is not None:
        kwargs["sparse_query"] = sparse_query
    if mode == "hybrid":
        kwargs["fusion_mode"] = fusion_mode
    raw = db.vector_search(mode, k, **kwargs)
    by_id = {unit.node_id: unit for unit in units}
    hits: list[SearchHit] = []
    for rank, item in enumerate(raw, start=1):
        unit = by_id.get(int(item.node_id))
        if unit is None:
            continue
        hits.append(
            SearchHit(
                node_id=unit.node_id,
                key=unit.key,
                score=float(item.score),
                rank=rank,
                document_id=unit.document_id,
                relative_path=unit.relative_path,
                text=unit.text,
            )
        )
    return hits


def exhaustive_rank(
    units: list[StoredUnit],
    *,
    mode: str,
    dense_query: list[float] | None = None,
    sparse_query: list[tuple[int, float]] | None = None,
) -> list[SearchHit]:
    scored: list[tuple[float, StoredUnit]] = []
    for unit in units:
        score = _score(unit, mode, dense_query, sparse_query)
        scored.append((score, unit))
    scored.sort(key=lambda item: item[0], reverse=True)
    hits: list[SearchHit] = []
    for rank, (score, unit) in enumerate(scored, start=1):
        hits.append(
            SearchHit(
                node_id=unit.node_id,
                key=unit.key,
                score=score,
                rank=rank,
                document_id=unit.document_id,
                relative_path=unit.relative_path,
                text=unit.text,
            )
        )
    return hits


RRF_K = 60


def rrf_fuse(
    rankings: list[list[SearchHit]],
    *,
    k: int | None = None,
    rrf_k: int = RRF_K,
) -> list[SearchHit]:
    scores: dict[str, float] = {}
    chosen: dict[str, SearchHit] = {}
    for ranking in rankings:
        for hit in ranking:
            scores[hit.key] = scores.get(hit.key, 0.0) + 1.0 / (rrf_k + hit.rank)
            previous = chosen.get(hit.key)
            if previous is None or hit.rank < previous.rank:
                chosen[hit.key] = hit
    ordered = sorted(chosen.values(), key=lambda hit: (-scores[hit.key], hit.key))
    if k is not None:
        ordered = ordered[:k]
    return [
        SearchHit(
            node_id=hit.node_id,
            key=hit.key,
            score=scores[hit.key],
            rank=rank,
            document_id=hit.document_id,
            relative_path=hit.relative_path,
            text=hit.text,
        )
        for rank, hit in enumerate(ordered, start=1)
    ]


def union_pool(rankings: list[list[SearchHit]], *, per_list: int) -> list[SearchHit]:
    clipped = [[hit for hit in ranking if hit.rank <= per_list] for ranking in rankings]
    return rrf_fuse(clipped)


def encode_query(
    query: str,
    *,
    dense: DenseEncoder,
    sparse: LexicalSparseEncoder,
) -> tuple[list[float], list[tuple[int, float]]]:
    return dense.embed([query])[0], sparse.embed([query])[0]


def _score(
    unit: StoredUnit,
    mode: str,
    dense_query: list[float] | None,
    sparse_query: list[tuple[int, float]] | None,
) -> float:
    dense_score = 0.0
    sparse_score = 0.0
    if dense_query is not None and unit.dense is not None:
        dense_score = cosine(dense_query, unit.dense)
    if sparse_query is not None and unit.sparse is not None:
        sparse_score = sparse_dot(sparse_query, unit.sparse)
    if mode == "dense":
        return dense_score
    if mode == "sparse":
        return sparse_score
    return dense_score + sparse_score
