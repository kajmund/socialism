"""Deterministic expansion decision. No Jev. Rule is a priori, not fitted."""

from __future__ import annotations

from overgraph_ingest.retrieval.search import SearchHit

NEVER = "never"
ALWAYS = "always"
DISAGREE = "dense_sparse_disagree"
DECISION_VARIANTS = (NEVER, ALWAYS, DISAGREE)
DISAGREE_TOP_N = 20
DISAGREE_MIN_JACCARD = 0.25
JACCARD_ROUTING = "rejected"


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def dense_sparse_disagree(
    dense_hits: list[SearchHit],
    sparse_hits: list[SearchHit],
    *,
    top_n: int = DISAGREE_TOP_N,
    min_jaccard: float = DISAGREE_MIN_JACCARD,
) -> bool:
    dense_keys = {hit.key for hit in dense_hits[:top_n]}
    sparse_keys = {hit.key for hit in sparse_hits[:top_n]}
    return jaccard(dense_keys, sparse_keys) < min_jaccard


def should_expand(
    variant: str,
    dense_hits: list[SearchHit],
    sparse_hits: list[SearchHit],
) -> bool:
    if variant == NEVER:
        return False
    if variant == ALWAYS:
        return True
    if variant == DISAGREE:
        return dense_sparse_disagree(dense_hits, sparse_hits)
    raise ValueError(f"unsupported decision variant {variant!r}")
