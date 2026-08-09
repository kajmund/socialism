"""Unit tests for SSR cosine / PMF / rate_texts (mocked embeddings)."""

from __future__ import annotations

import math

import pytest

from app.services.ssr import (
    ANCHOR_SET_VERSION,
    clear_embedding_cache,
    rate_texts,
    set_embedder,
    similarities_to_pmf,
    tone_anchors,
)
from app.services.ssr.embeddings import (
    cache_get,
    drop_memory_cache,
    embedding_cache_size,
    list_embedding_cache_entries,
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


def _tone_content_embedder():
    """Map by statement text so cache split batches still work."""
    anchors = tone_anchors(locale="sv")
    index_by_statement = {s: i for i, s in enumerate(anchors.statements)}

    async def _fake(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            idx = index_by_statement.get(text)
            if idx is None:
                # Judgment near first anchor (strongly negative)
                out.append([1.0, 0.0, 0.0, 0.0, 0.0])
            else:
                v = [0.0] * 5
                v[idx] = 1.0
                out.append(v)
        return out

    return _fake


@pytest.mark.asyncio
async def test_rate_texts_prefers_matching_anchor():
    """Deterministic unit vectors: judgment aligns with 'strongly negative' anchor."""
    set_embedder(_tone_content_embedder())
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


@pytest.mark.asyncio
async def test_anchor_embeddings_are_cached():
    calls: list[list[str]] = []

    base = _tone_content_embedder()

    async def _tracking(texts: list[str]) -> list[list[float]]:
        calls.append(list(texts))
        return await base(texts)

    clear_embedding_cache()
    set_embedder(_tracking)
    try:
        anchors = tone_anchors(locale="sv")
        await rate_texts(["första"], anchors)
        assert embedding_cache_size() == len(anchors.statements)
        assert len(calls) == 1
        assert len(calls[0]) == 1 + len(anchors.statements)
        assert len(list_embedding_cache_entries()) == len(anchors.statements)

        # Drop memory — disk should still serve hits.
        drop_memory_cache()
        assert cache_get(anchors.statements[0]) is not None

        await rate_texts(["andra"], anchors)
        assert len(calls) == 2
        # Second call: only the new reaction text (anchors served from cache).
        assert calls[1] == ["andra"]
        assert embedding_cache_size() == len(anchors.statements)
    finally:
        set_embedder(None)
        clear_embedding_cache()


@pytest.mark.asyncio
async def test_embedding_cache_api_list_and_clear(client):
    base = _tone_content_embedder()
    set_embedder(base)
    try:
        await rate_texts(["api-cache"], tone_anchors(locale="sv"))
        listed = await client.get("/embeddings/cache")
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["count"] >= 5
        assert body["entries"][0]["text"]
        assert "vector" not in body["entries"][0]

        cleared = await client.delete("/embeddings/cache")
        assert cleared.status_code == 200
        assert cleared.json()["cleared"] >= 5
        empty = await client.get("/embeddings/cache")
        assert empty.json()["count"] == 0
    finally:
        set_embedder(None)
        clear_embedding_cache()


def test_cache_put_survives_concurrent_writes():
    """Parallel cache_put for the same key must not raise FileNotFoundError."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from app.services.ssr.embeddings import cache_put

    clear_embedding_cache()
    text = "Concurrent anchor write stress"
    vec = [0.2] * 16
    errors: list[str] = []

    def _write() -> None:
        try:
            cache_put(text, vec)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=50) as pool:
        futures = [pool.submit(_write) for _ in range(50)]
        for future in as_completed(futures):
            future.result()

    assert errors == []
    assert cache_get(text) == vec
