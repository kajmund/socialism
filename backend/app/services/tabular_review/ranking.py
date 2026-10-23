"""Deterministic SSR ranking: raw cosine similarity, never a probability."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.knowledge.units import TextUnit
from app.services.ssr.similarity import cosine_similarity
from app.services.tabular_review.locators import source_locator
from app.services.tabular_review.types import (
    DEFAULT_CANDIDATE_LIMIT,
    HIT,
    NEGATIVE_HIT,
    NO_HIT,
    UNKNOWN,
    CellDecision,
    CellPolarity,
    RankedCandidate,
)


def unit_similarity(unit_vector: Sequence[float], anchor_vectors: Sequence[Sequence[float]]) -> float:
    """Best cosine between one TextUnit and the column's anchor statements."""
    if not anchor_vectors:
        return 0.0
    return max(cosine_similarity(list(unit_vector), list(anchor)) for anchor in anchor_vectors)


def rank_candidates(
    candidates: Sequence[RankedCandidate],
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> tuple[RankedCandidate, ...]:
    ordered = sorted(candidates, key=lambda item: (-item.similarity, item.text_unit_id))
    if limit < 1:
        return tuple(ordered)
    return tuple(ordered[:limit])


def decide_cell(
    ranked: Sequence[RankedCandidate],
    *,
    threshold: float,
    polarity: CellPolarity,
    allow_abstain: bool,
    abstain_margin: float | None,
) -> CellDecision:
    """Absence of a hit is unknown/no_hit — never negative evidence."""
    if not ranked or ranked[0].similarity < threshold:
        return CellDecision(
            status=NO_HIT,
            selected=None,
            candidates=tuple(ranked),
            threshold=threshold,
        )
    if allow_abstain and abstain_margin is not None and len(ranked) >= 2:
        gap = ranked[0].similarity - ranked[1].similarity
        if gap < abstain_margin:
            return CellDecision(
                status=UNKNOWN,
                selected=None,
                candidates=tuple(ranked),
                threshold=threshold,
            )
    status = NEGATIVE_HIT if polarity == "negative" else HIT
    return CellDecision(
        status=status,
        selected=ranked[0],
        candidates=tuple(ranked),
        threshold=threshold,
    )


@dataclass(frozen=True)
class ColumnScoreOptions:
    polarity: CellPolarity
    threshold: float
    allow_abstain: bool = False
    abstain_margin: float | None = None
    limit: int = DEFAULT_CANDIDATE_LIMIT


def score_document_column(
    units: Sequence[TextUnit],
    embeddings: dict[str, list[float]],
    anchor_vectors: Sequence[Sequence[float]],
    options: ColumnScoreOptions,
) -> CellDecision:
    polarity = options.polarity
    threshold = options.threshold
    allow_abstain = options.allow_abstain
    abstain_margin = options.abstain_margin
    limit = options.limit
    scored: list[RankedCandidate] = []
    for unit in units:
        vector = embeddings.get(unit.id)
        if vector is None:
            continue
        scored.append(
            RankedCandidate(
                text_unit_id=unit.id,
                exact_text=unit.text,
                similarity=unit_similarity(vector, anchor_vectors),
                polarity=polarity,
                source=source_locator(unit),
            )
        )
    ranked = rank_candidates(scored, limit=limit)
    return decide_cell(
        ranked,
        threshold=threshold,
        polarity=polarity,
        allow_abstain=allow_abstain,
        abstain_margin=abstain_margin,
    )
