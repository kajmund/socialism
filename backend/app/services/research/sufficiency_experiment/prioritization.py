"""B3 pair-prioritisation interface. Ordering only; Jev still decides contradictions.

Strategies are pure rankings over the existing candidate universe. A later SSR
arm can plug in by providing another `PairOrdering` implementation without
changing SWE execution, budgets or the A3 decision contract.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    PairCandidate,
)

PairOrdering = str  # "current" | "metadata" | "embedding"

_NEGATIVE = re.compile(
    r"\b(inte|förbjud\w*|otillå\w*|nek\w*|endast|senast|stäng\w*|motbevis\w*)\b",
    re.IGNORECASE,
)
_POSITIVE = re.compile(
    r"\b(får|tillåt\w*|gäller|tillämpar|öppen|måste|ska)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d+")


class PairScorer(Protocol):
    async def score(
        self,
        candidates: Sequence[PairCandidate],
        claims: Mapping[str, ClaimCandidate],
    ) -> Mapping[str, float]: ...


async def prioritize_pairs(
    candidates: Sequence[PairCandidate],
    claims: Mapping[str, ClaimCandidate],
    *,
    ordering: PairOrdering,
    embedding_provider: EmbeddingProvider | None = None,
) -> tuple[PairCandidate, ...]:
    if ordering == "current":
        return tuple(candidates)
    if ordering == "metadata":
        return _rank(candidates, _metadata_scores(candidates, claims))
    if ordering == "embedding":
        if embedding_provider is None:
            raise ValueError("embedding ordering requires an embedding provider")
        cosine = await _embedding_scores(candidates, claims, embedding_provider)
        return _rank(candidates, _combine(cosine, _metadata_scores(candidates, claims)))
    raise ValueError(f"unknown pair ordering: {ordering}")


def _metadata_scores(
    candidates: Sequence[PairCandidate],
    claims: Mapping[str, ClaimCandidate],
) -> dict[str, float]:
    raw = {pair.pair_id: _metadata_raw(pair, claims) for pair in candidates}
    ceiling = max(raw.values(), default=0.0) or 1.0
    return {pair_id: value / ceiling for pair_id, value in raw.items()}


def _metadata_raw(
    pair: PairCandidate,
    claims: Mapping[str, ClaimCandidate],
) -> float:
    features = dict(pair.features)
    left = claims.get(pair.left_claim_id)
    right = claims.get(pair.right_claim_id)
    independence = (
        1.0
        if left is not None
        and right is not None
        and left.source_id
        and right.source_id
        and left.source_id != right.source_id
        else 0.0
    )
    polarity = (
        1.0
        if left is not None and right is not None and _opposite_polarity(left.text, right.text)
        else 0.0
    )
    value_diff = (
        1.0
        if left is not None and right is not None and _value_difference(left.text, right.text)
        else 0.0
    )
    score = (
        1.5 * features.get("entity", 0.0)
        + 1.5 * features.get("definition", 0.0)
        + min(features.get("rarity", 0.0), 10.0) / 10.0
        + 0.5 * features.get("question", 0.0)
        + 1.5 * independence
        + 2.0 * polarity
        + 1.0 * value_diff
    )
    return score * features.get("canonical_downweight", 1.0)


def _opposite_polarity(left: str, right: str) -> bool:
    left_negative = bool(_NEGATIVE.search(left))
    right_negative = bool(_NEGATIVE.search(right))
    left_positive = bool(_POSITIVE.search(left))
    right_positive = bool(_POSITIVE.search(right))
    return (left_negative and right_positive and not right_negative) or (
        right_negative and left_positive and not left_negative
    )


def _value_difference(left: str, right: str) -> bool:
    left_values = set(_NUMBER.findall(left))
    right_values = set(_NUMBER.findall(right))
    return bool(left_values and right_values and left_values != right_values)


async def _embedding_scores(
    candidates: Sequence[PairCandidate],
    claims: Mapping[str, ClaimCandidate],
    provider: EmbeddingProvider,
) -> dict[str, float]:
    claim_ids = sorted({pair.left_claim_id for pair in candidates} | {pair.right_claim_id for pair in candidates})
    texts = [claims[claim_id].text for claim_id in claim_ids]
    vectors = await provider.embed(texts)
    by_id = dict(zip(claim_ids, vectors, strict=True))
    out: dict[str, float] = {}
    for pair in candidates:
        left = by_id.get(pair.left_claim_id)
        right = by_id.get(pair.right_claim_id)
        out[pair.pair_id] = _cosine(left, right) if left is not None and right is not None else 0.0
    return out


def _combine(
    cosine: Mapping[str, float], metadata: Mapping[str, float]
) -> dict[str, float]:
    return {
        pair_id: 0.7 * cosine.get(pair_id, 0.0) + 0.3 * metadata.get(pair_id, 0.0)
        for pair_id in cosine
    }


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _rank(
    candidates: Sequence[PairCandidate], scores: Mapping[str, float]
) -> tuple[PairCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda pair: (-scores.get(pair.pair_id, 0.0), pair.pair_id),
        )
    )
