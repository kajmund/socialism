"""Semantic Similarity Rating (SSR) — embed texts against Likert/style anchors."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.ssr.anchors import (
    ANCHOR_SET_VERSION,
    STYLE_LABELS,
    STYLE_UNCLASSIFIED,
    AnchorSet,
    style_anchors,
    tone_anchors,
    tone_labels,
)
from app.services.ssr.embeddings import (
    cache_get,
    cache_put,
    clear_embedding_cache,
    embed_texts,
    embed_texts_cached,
    list_embedding_cache_entries,
    set_embedder,
)
from app.services.ssr.similarity import (
    aggregate_pmfs,
    cosine_similarity,
    similarities_to_pmf,
)

__all__ = [
    "ANCHOR_SET_VERSION",
    "STYLE_LABELS",
    "STYLE_UNCLASSIFIED",
    "AnchorSet",
    "SSRResult",
    "aggregate_pmfs",
    "clear_embedding_cache",
    "cosine_similarity",
    "embed_texts",
    "embed_texts_cached",
    "list_embedding_cache_entries",
    "rate_texts",
    "set_embedder",
    "similarities_to_pmf",
    "style_anchors",
    "tone_anchors",
    "tone_labels",
]


@dataclass
class SSRResult:
    shares: dict[str, float]
    per_text_pmfs: list[dict[str, float]]
    anchor_set_name: str
    anchor_set_version: str
    labels: tuple[str, ...]


async def rate_texts(
    texts: list[str],
    anchor_set: AnchorSet,
    *,
    temperature: float = 1.0,
) -> SSRResult:
    """Embed texts + anchors, cosine → soft PMF per text, mean shares.

    Anchor embeddings are process-cached by (embedding_model, statement).
    Reaction texts are never cached (usually unique per run).
    """
    labels = anchor_set.labels
    empty_shares = {lab: 0.0 for lab in labels}
    if not texts:
        return SSRResult(
            shares=empty_shares,
            per_text_pmfs=[],
            anchor_set_name=anchor_set.name,
            anchor_set_version=anchor_set.version,
            labels=labels,
        )

    statements = list(anchor_set.statements)
    cached_anchors: list[list[float] | None] = [cache_get(s) for s in statements]
    missing = [
        (i, s) for i, (s, vec) in enumerate(zip(statements, cached_anchors, strict=True)) if vec is None
    ]
    # Single round-trip: reaction texts + only uncached anchors.
    to_embed = [*texts, *[s for _, s in missing]]
    vectors = await embed_texts(to_embed)
    text_vecs = vectors[: len(texts)]
    fresh_anchors = vectors[len(texts) :]
    if len(fresh_anchors) != len(missing):
        raise RuntimeError(
            f"embed_texts returned {len(fresh_anchors)} anchor vectors "
            f"for {len(missing)} misses"
        )
    for (idx, statement), vec in zip(missing, fresh_anchors, strict=True):
        cache_put(statement, vec)
        cached_anchors[idx] = vec
    anchor_vecs = [v for v in cached_anchors if v is not None]
    if len(anchor_vecs) != len(statements):
        raise RuntimeError("anchor embedding cache stitch incomplete")

    per_text: list[dict[str, float]] = []
    pmf_rows: list[list[float]] = []
    for tv in text_vecs:
        sims = [cosine_similarity(tv, av) for av in anchor_vecs]
        pmf = similarities_to_pmf(sims, temperature=temperature)
        pmf_rows.append(pmf)
        per_text.append({lab: pmf[i] for i, lab in enumerate(labels)})

    return SSRResult(
        shares=aggregate_pmfs(pmf_rows, labels),
        per_text_pmfs=per_text,
        anchor_set_name=anchor_set.name,
        anchor_set_version=anchor_set.version,
        labels=labels,
    )
