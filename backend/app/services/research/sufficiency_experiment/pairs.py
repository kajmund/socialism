"""Pair candidates for A3. Generation only: no Jev judgement here.

Three strategies are measured separately: deterministic anchors, embedding
neighbours, and a hybrid union. The budget is applied after a strategy has
produced its candidate set, so recall can be reported before and after the
budget. No claim that shares no signal is silently dropped: every candidate
carries its features and every selected pair has a rank.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from time import perf_counter

from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.research.models import ResearchNeed
from app.services.research.sufficiency_experiment.prioritization import (
    prioritize_pairs,
)
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    ExperimentConfig,
    PairCandidate,
    PairSelection,
    PairStrategy,
)

_STOPWORDS = frozenset(
    {
        "och", "i", "att", "det", "som", "en", "ett", "på", "är", "av", "för",
        "med", "den", "till", "inte", "om", "har", "de", "kan", "vid", "samt",
        "eller", "så", "ska", "från", "var", "vara", "detta", "denna", "dessa",
        "sig", "sin", "sitt", "sina", "under", "över", "mellan", "mot", "utan",
        "enligt", "gäller", "gälla", "samma", "även", "där", "här", "nu", "då",
        "första", "andra", "tredje", "nummer", "parterna", "avtalet",
    }
)


async def select_pairs(
    claims: Sequence[ClaimCandidate],
    needs: Sequence[ResearchNeed],
    *,
    strategy: PairStrategy,
    config: ExperimentConfig,
    embedding_provider: EmbeddingProvider | None = None,
) -> PairSelection:
    started = perf_counter()
    usable = [claim for claim in claims if claim.extraction_status == "extracted"]
    questions = {need.id: _tokens(need.question) for need in needs}
    deterministic: list[PairCandidate] = []
    embedding_calls = 0
    embedding_texts = 0
    if strategy in {"deterministic", "hybrid"}:
        deterministic = _deterministic(usable, questions)
    embedded: list[PairCandidate] = []
    embedding_ms = 0.0
    if strategy in {"embeddings", "hybrid"}:
        if embedding_provider is None:
            raise ValueError(f"strategy {strategy!r} requires an embedding provider")
        embedding_started = perf_counter()
        embedded, embedding_texts = await _embedded(usable, embedding_provider, config)
        embedding_ms = (perf_counter() - embedding_started) * 1000
        embedding_calls = 1
    candidates = _combine(strategy, deterministic, embedded)
    selected = _apply_budget(candidates, config)
    return PairSelection(
        strategy=strategy,
        candidates=tuple(candidates),
        selected=tuple(selected),
        budget=config.max_pairs_per_need,
        omitted_by_budget=len(candidates) - len(selected),
        input_claims=len(usable),
        latency_ms=(perf_counter() - started) * 1000,
        embedding_calls=embedding_calls,
        embedding_texts=embedding_texts,
        embedding_ms=embedding_ms,
    )


def _deterministic(
    claims: Sequence[ClaimCandidate],
    questions: Mapping[str, frozenset[str]],
) -> list[PairCandidate]:
    tokens = {claim.claim_id: _tokens(claim.text) for claim in claims}
    frequency: Counter[str] = Counter(
        token for values in tokens.values() for token in values
    )
    pairs: list[PairCandidate] = []
    for index, left in enumerate(claims):
        for right in claims[index + 1 :]:
            need_id = _shared_need(left, right)
            if need_id is None:
                continue
            pair = _deterministic_pair(
                left,
                right,
                need_id,
                tokens=tokens,
                frequency=frequency,
                questions=questions,
            )
            if pair is not None:
                pairs.append(pair)
    pairs.sort(key=lambda item: (-item.score, item.pair_id))
    return pairs


def _deterministic_pair(
    left: ClaimCandidate,
    right: ClaimCandidate,
    need_id: str,
    *,
    tokens: Mapping[str, frozenset[str]],
    frequency: Mapping[str, int],
    questions: Mapping[str, frozenset[str]],
) -> PairCandidate | None:
    shared = tokens[left.claim_id] & tokens[right.claim_id]
    entity = _anchor(left.entity_id, right.entity_id)
    definition = _anchor(left.definition_id, right.definition_id)
    if not shared and not entity and not definition:
        return None
    rarity = sum(1.0 / frequency[token] for token in shared)
    question = len(shared & questions.get(need_id, frozenset()))
    canonical = left.canonical_key == right.canonical_key
    score = entity + definition + rarity + 0.5 * question
    if canonical:
        score *= 0.5
    features = (
        ("entity", round(entity, 4)),
        ("definition", round(definition, 4)),
        ("rarity", round(rarity, 4)),
        ("question", float(question)),
        ("canonical_downweight", 0.5 if canonical else 1.0),
    )
    return _pair(
        left,
        right,
        need_id,
        score=score,
        sources=("deterministic",),
        features=features,
    )


def _anchor(left: str | None, right: str | None) -> float:
    if left is None or right is None or left != right:
        return 0.0
    return 3.0


async def _embedded(
    claims: Sequence[ClaimCandidate],
    provider: EmbeddingProvider,
    config: ExperimentConfig,
) -> tuple[list[PairCandidate], int]:
    if not claims:
        return [], 0
    vectors = await provider.embed([claim.text for claim in claims])
    by_need: dict[str, list[int]] = {}
    for index, claim in enumerate(claims):
        for need_id in claim.research_need_ids:
            by_need.setdefault(need_id, []).append(index)
    pairs: dict[str, PairCandidate] = {}
    for need_id, indices in by_need.items():
        for position, left_index in enumerate(indices):
            scored = [
                (_cosine(vectors[left_index], vectors[right_index]), right_index)
                for right_index in indices
                if right_index != left_index
            ]
            scored.sort(reverse=True)
            for similarity, right_index in scored[: config.embedding_neighbors]:
                left = claims[left_index]
                right = claims[right_index]
                pair_id = _pair_id(left.claim_id, right.claim_id)
                if pair_id in pairs:
                    continue
                pairs[pair_id] = _pair(
                    left,
                    right,
                    need_id,
                    score=max(0.0, similarity),
                    sources=("embeddings",),
                    features=(("cosine", round(similarity, 4)),),
                )
    return sorted(pairs.values(), key=lambda item: (-item.score, item.pair_id)), len(claims)


def _combine(
    strategy: PairStrategy,
    deterministic: Sequence[PairCandidate],
    embedded: Sequence[PairCandidate],
) -> list[PairCandidate]:
    if strategy == "deterministic":
        return list(deterministic)
    if strategy == "embeddings":
        return list(embedded)
    merged: dict[str, PairCandidate] = {}
    for pair in deterministic:
        merged[pair.pair_id] = pair
    for pair in embedded:
        existing = merged.get(pair.pair_id)
        if existing is None:
            merged[pair.pair_id] = pair
            continue
        merged[pair.pair_id] = PairCandidate(
            pair_id=pair.pair_id,
            need_id=pair.need_id,
            left_claim_id=pair.left_claim_id,
            right_claim_id=pair.right_claim_id,
            score=existing.score + pair.score,
            sources=("deterministic", "embeddings"),
            features=existing.features + pair.features,
        )
    return sorted(merged.values(), key=lambda item: (-item.score, item.pair_id))


def _apply_budget(
    candidates: Sequence[PairCandidate],
    config: ExperimentConfig,
) -> list[PairCandidate]:
    per_need: dict[str, list[PairCandidate]] = {}
    for pair in candidates:
        per_need.setdefault(pair.need_id, []).append(pair)
    selected: list[PairCandidate] = []
    for rows in per_need.values():
        selected.extend(rows[: config.max_pairs_per_need])
    return sorted(selected, key=lambda item: (-item.score, item.pair_id))


def _shared_need(left: ClaimCandidate, right: ClaimCandidate) -> str | None:
    shared = set(left.research_need_ids) & set(right.research_need_ids)
    return sorted(shared)[0] if shared else None


def _pair(
    left: ClaimCandidate,
    right: ClaimCandidate,
    need_id: str,
    *,
    score: float,
    sources: tuple[str, ...],
    features: tuple[tuple[str, float], ...],
) -> PairCandidate:
    pair_id = _pair_id(left.claim_id, right.claim_id)
    return PairCandidate(
        pair_id=pair_id,
        need_id=need_id,
        left_claim_id=left.claim_id,
        right_claim_id=right.claim_id,
        score=round(score, 6),
        sources=sources,
        features=features,
    )


def _pair_id(left: str, right: str) -> str:
    return "|".join(sorted((left, right)))


def _tokens(text: str) -> frozenset[str]:
    words = (
        "".join(character if character.isalnum() else " " for character in text.lower())
        .split()
    )
    return frozenset(word for word in words if word not in _STOPWORDS and len(word) > 1)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


async def select_ordered_pairs(
    claims: Sequence[ClaimCandidate],
    needs: Sequence[ResearchNeed],
    claims_by_id: Mapping[str, ClaimCandidate],
    *,
    strategy: PairStrategy,
    ordering: str,
    config: ExperimentConfig,
    embedding_provider: EmbeddingProvider | None = None,
) -> PairSelection:
    """Select candidates, optionally re-rank them, then apply the same budget."""
    selection = await select_pairs(
        claims,
        needs,
        strategy=strategy,
        config=config,
        embedding_provider=embedding_provider,
    )
    if ordering == "current":
        return selection
    started = perf_counter()
    ranked = await prioritize_pairs(
        selection.candidates, claims_by_id, ordering=ordering
    )
    prioritization_ms = (perf_counter() - started) * 1000
    per_need: dict[str, list[PairCandidate]] = {}
    for pair in ranked:
        per_need.setdefault(pair.need_id, []).append(pair)
    selected = tuple(
        pair
        for rows in per_need.values()
        for pair in rows[: config.max_pairs_per_need]
    )
    return PairSelection(
        strategy=selection.strategy,
        candidates=selection.candidates,
        selected=selected,
        budget=selection.budget,
        omitted_by_budget=len(selection.candidates) - len(selected),
        input_claims=selection.input_claims,
        latency_ms=selection.latency_ms,
        embedding_calls=selection.embedding_calls,
        embedding_texts=selection.embedding_texts,
        embedding_ms=selection.embedding_ms,
        prioritization_ms=prioritization_ms,
    )
