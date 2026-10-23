"""Opt-in SSR match against active clause AnchorSets. Not a probability."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.isolation import assert_visible
from app.services.overgraph.labels import TEXT_UNIT
from app.services.ssr.similarity import cosine_similarity

from app.services.clause_ssr.anchors import anchor_is_matchable, list_anchors
from app.services.clause_ssr.graph import prop_str, require_node
from app.services.clause_ssr.select import list_anchor_sets
from app.services.clause_ssr.types import (
    Anchor,
    CategoryScore,
    EmbeddingSpec,
    MatchHit,
    MatchResult,
)

MIN_SIMILARITY = 0.25
MIN_MARGIN = 0.04
SUPPORT_THRESHOLD = 0.45


def match_query(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    embedding: EmbeddingSpec,
    vector: list[float] | None = None,
    text_unit_id: str | None = None,
    k: int = 8,
    set_id: str | None = None,
) -> MatchResult:
    query = _query_vector(
        catalog,
        scope=scope,
        embedding=embedding,
        vector=vector,
        text_unit_id=text_unit_id,
    )
    members = _active_members(catalog, scope, embedding, set_id)
    hits = _rank_hits(query, members)[:k]
    scores = _category_scores(query, members)
    labels, abstained, reason = _decide_labels(scores)
    return MatchResult(
        top_k=tuple(hits),
        category_scores=tuple(scores),
        labels=labels,
        abstained=abstained,
        abstain_reason=reason,
        embedding=embedding,
    )


def _query_vector(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    embedding: EmbeddingSpec,
    vector: list[float] | None,
    text_unit_id: str | None,
) -> list[float]:
    if text_unit_id is not None:
        unit = require_node(catalog, TEXT_UNIT, text_unit_id)
        assert_visible(prop_str(unit, "scope_key"), scope.customer_id)
        if unit.dense_vector is None:
            raise ValueError("text unit has no stored embedding")
        if len(unit.dense_vector) != embedding.dimension:
            raise ValueError("text unit embedding dimension does not match")
        return list(unit.dense_vector)
    if vector is None:
        raise ValueError("match requires a text_unit_id or a dense_vector")
    if len(vector) != embedding.dimension:
        raise ValueError("query embedding dimension does not match")
    return list(vector)


def _active_members(
    catalog: Catalog,
    scope: KnowledgeTenantScope,
    embedding: EmbeddingSpec,
    set_id: str | None,
) -> list[Anchor]:
    sets = list_anchor_sets(catalog, customer_id=scope.customer_id, active_only=True)
    if set_id is not None:
        sets = [item for item in sets if item.id == set_id]
    allowed: set[str] = set()
    for item in sets:
        if not _same_embedding(item.embedding, embedding):
            continue
        allowed.update(item.member_ids)
    if not allowed:
        raise ValueError("no active anchor set matches the embedding spec")
    members: list[Anchor] = []
    for anchor in list_anchors(catalog, customer_id=scope.customer_id, statuses=("draft", "active")):
        if anchor.id not in allowed or anchor.vector is None:
            continue
        if not _same_embedding(anchor.embedding, embedding):
            continue
        if not anchor_is_matchable(catalog, anchor):
            continue
        members.append(anchor)
    return members


def _rank_hits(query: list[float], members: list[Anchor]) -> list[MatchHit]:
    hits = [_hit(query, anchor) for anchor in members]
    hits.sort(key=lambda item: item.cosine_similarity, reverse=True)
    return hits


def _hit(query: list[float], anchor: Anchor) -> MatchHit:
    if anchor.vector is None:
        raise ValueError("anchor is missing a vector")
    return MatchHit(
        anchor_id=anchor.id,
        classification_id=anchor.classification_id,
        category=anchor.category,
        polarity=anchor.polarity,
        cosine_similarity=cosine_similarity(query, list(anchor.vector)),
        source_unit_id=anchor.source_unit_id,
        content_hash=anchor.content_hash,
    )


def _category_scores(query: list[float], members: list[Anchor]) -> list[CategoryScore]:
    grouped: dict[str, list[Anchor]] = {}
    for anchor in members:
        grouped.setdefault(anchor.category, []).append(anchor)
    scores = [_score_category(query, category, grouped[category]) for category in grouped]
    scores.sort(key=lambda item: item.score, reverse=True)
    for index, item in enumerate(scores):
        rival = scores[1].score if index == 0 and len(scores) > 1 else (
            scores[0].score if scores else 0.0
        )
        if index == 0 and len(scores) > 1:
            margin = item.score - rival
        elif scores:
            margin = item.score - scores[0].score
        else:
            margin = 0.0
        scores[index] = CategoryScore(
            category=item.category,
            score=item.score,
            margin=margin,
            support_count=item.support_count,
            independent_support=item.independent_support,
            negative_signal=item.negative_signal,
            top_similarity=item.top_similarity,
        )
    return scores


def _score_category(query: list[float], category: str, members: list[Anchor]) -> CategoryScore:
    positives = [_sim(query, item) for item in members if item.polarity == "positive"]
    negatives = [_sim(query, item) for item in members if item.polarity == "negative"]
    pos = _mean(positives)
    neg = _mean(negatives)
    score = pos - (0.5 * neg if negatives else 0.0)
    support = [item for item in members if item.polarity == "positive" and _sim(query, item) >= SUPPORT_THRESHOLD]
    hashes = {item.content_hash for item in support if item.content_hash}
    return CategoryScore(
        category=category,
        score=score,
        margin=0.0,
        support_count=len(support),
        independent_support=len(hashes),
        negative_signal=max(negatives) if negatives else 0.0,
        top_similarity=max(positives) if positives else 0.0,
    )


def _decide_labels(
    scores: list[CategoryScore],
) -> tuple[tuple[str, ...], bool, str | None]:
    if not scores:
        return (), True, "no_anchors"
    best = scores[0]
    if best.top_similarity < MIN_SIMILARITY:
        return (), True, "low_similarity"
    if best.margin < MIN_MARGIN and len(scores) > 1:
        return (), True, "low_margin"
    labels = [item.category for item in scores if item.score >= best.score - MIN_MARGIN]
    if best.score <= 0:
        return (), True, "negative_score"
    return tuple(labels), False, None


def _sim(query: list[float], anchor: Anchor) -> float:
    if anchor.vector is None:
        return 0.0
    return cosine_similarity(query, list(anchor.vector))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _same_embedding(left: EmbeddingSpec, right: EmbeddingSpec) -> bool:
    return (
        left.model == right.model
        and left.revision == right.revision
        and left.dimension == right.dimension
    )

