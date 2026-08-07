"""Unit tests for SSR cosine / PMF / rate_texts (mocked embeddings)."""

from __future__ import annotations

import math

import pytest

from app.services.ssr import (
    ANCHOR_SET_VERSION,
    rate_texts,
    set_embedder,
    similarities_to_pmf,
    tone_anchors,
)
from app.services.ssr.similarity import aggregate_pmfs, cosine_similarity


def test_cosine_identical_and_orthogonal():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 1.0], [-1.0, -1.0]) == pytest.approx(-1.0)


def test_similarities_to_pmf_sums_to_one():
    pmf = similarities_to_pmf([0.1, 0.9, 0.2])
    assert len(pmf) == 3
    assert sum(pmf) == pytest.approx(1.0)
    assert pmf[1] == max(pmf)


def test_aggregate_pmfs_mean():
    labels = ("a", "b")
    shares = aggregate_pmfs([[1.0, 0.0], [0.0, 1.0]], labels)
    assert shares["a"] == pytest.approx(0.5)
    assert shares["b"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_rate_texts_prefers_matching_anchor():
    """Deterministic unit vectors: judgment aligns with 'strongly negative' anchor."""

    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        # texts = [judgment..., *5 anchors]
        out: list[list[float]] = []
        for i, _ in enumerate(texts):
            n_texts = len(texts) - 5
            if i < n_texts:
                # Judgment near first anchor (strongly negative)
                out.append([1.0, 0.0, 0.0, 0.0, 0.0])
            else:
                # One-hot anchors in 5-D
                idx = i - n_texts
                v = [0.0] * 5
                v[idx] = 1.0
                out.append(v)
        return out

    set_embedder(_fake_embed)
    try:
        result = await rate_texts(
            ["Mycket negativ och kritisk hållning."],
            tone_anchors(locale="sv"),
        )
        assert result.anchor_set_version == ANCHOR_SET_VERSION
        assert result.shares["Starkt negativ"] == max(result.shares.values())
        assert result.shares["Starkt negativ"] > 0.35
        assert math.isclose(sum(result.shares.values()), 1.0)
        assert result.per_text_pmfs[0]["Starkt negativ"] == max(
            result.per_text_pmfs[0].values()
        )
    finally:
        set_embedder(None)


@pytest.mark.asyncio
async def test_rate_texts_empty():
    async def _should_not_run(_texts: list[str]) -> list[list[float]]:
        raise AssertionError("should not embed")

    set_embedder(_should_not_run)
    try:
        result = await rate_texts([], tone_anchors(locale="sv"))
        assert all(v == 0.0 for v in result.shares.values())
        assert result.per_text_pmfs == []
    finally:
        set_embedder(None)
