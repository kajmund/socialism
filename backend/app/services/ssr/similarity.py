"""Cosine similarity and soft PMF helpers for Semantic Similarity Rating."""

from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    if not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na) * math.sqrt(nb)
    if denom <= 0.0:
        return 0.0
    return dot / denom


def similarities_to_pmf(
    similarities: list[float],
    *,
    temperature: float = 1.0,
) -> list[float]:
    """Softmax over similarities (shifted for numeric stability)."""
    if not similarities:
        return []
    if temperature <= 0.0:
        raise ValueError("temperature must be > 0")
    scaled = [s / temperature for s in similarities]
    peak = max(scaled)
    exps = [math.exp(s - peak) for s in scaled]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def aggregate_pmfs(
    pmfs: list[list[float]],
    labels: tuple[str, ...] | list[str],
) -> dict[str, float]:
    """Mean PMF across texts → label shares (sums to 1 when pmfs non-empty)."""
    n_labels = len(labels)
    if n_labels == 0:
        return {}
    if not pmfs:
        return {lab: 0.0 for lab in labels}
    acc = [0.0] * n_labels
    for pmf in pmfs:
        if len(pmf) != n_labels:
            raise ValueError(f"pmf length {len(pmf)} != labels {n_labels}")
        for i, p in enumerate(pmf):
            acc[i] += p
    n = len(pmfs)
    return {lab: acc[i] / n for i, lab in enumerate(labels)}
