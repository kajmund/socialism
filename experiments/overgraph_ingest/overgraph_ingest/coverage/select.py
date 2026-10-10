"""Gold-blind candidate selection. Does not classify."""

from __future__ import annotations

from overgraph_ingest.retrieval.search import SearchHit


def global_top_k(ranked: list[SearchHit], k: int) -> list[SearchHit]:
    return [hit for hit in ranked if hit.rank <= k][:k]


def document_scoped(ranked: list[SearchHit], n: int) -> list[SearchHit]:
    buckets: dict[str, list[SearchHit]] = {}
    for hit in ranked:
        bucket = buckets.setdefault(hit.relative_path, [])
        if len(bucket) < n:
            bucket.append(hit)
    return _round_robin(buckets)


def progressive_unexamined(
    ranked: list[SearchHit],
    *,
    global_k: int,
    per_document: int,
) -> tuple[list[SearchHit], list[SearchHit]]:
    first = global_top_k(ranked, global_k)
    seen_docs = {hit.relative_path for hit in first}
    extra = [
        hit
        for hit in document_scoped(ranked, per_document)
        if hit.relative_path not in seen_docs
    ]
    return first, extra


def _round_robin(buckets: dict[str, list[SearchHit]]) -> list[SearchHit]:
    depth = max((len(bucket) for bucket in buckets.values()), default=0)
    ordered: list[SearchHit] = []
    for index in range(depth):
        layer = [bucket[index] for bucket in buckets.values() if len(bucket) > index]
        layer.sort(key=lambda hit: (hit.rank, hit.key))
        ordered.extend(layer)
    return ordered
