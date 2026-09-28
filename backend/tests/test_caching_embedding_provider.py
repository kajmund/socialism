"""CachingEmbeddingProvider hits memory after the first embed."""

from __future__ import annotations

import asyncio

from app.services.knowledge.embeddings import CachingEmbeddingProvider
from tests.knowledge_fakes import FakeEmbeddingProvider


class _GateProvider:
    provider_id = "fake"
    model = "fake-tokens"
    dimension = 1

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.started.set()
        await self.release.wait()
        self.in_flight -= 1
        return [[float(len(text))] for text in texts]


async def test_cache_returns_same_vector_without_second_inner_call():
    inner = FakeEmbeddingProvider()
    cached = CachingEmbeddingProvider(inner)
    first = await cached.embed(["alpha", "beta"])
    second = await cached.embed(["beta", "alpha", "beta"])
    assert second == [first[1], first[0], first[1]]
    assert inner.calls == [("alpha", "beta")]


async def test_cache_batches_only_missing_texts():
    inner = FakeEmbeddingProvider()
    cached = CachingEmbeddingProvider(inner)
    await cached.embed(["alpha"])
    await cached.embed(["alpha", "gamma"])
    assert inner.calls == [("alpha",), ("gamma",)]


async def test_empty_embed_does_not_call_inner():
    inner = FakeEmbeddingProvider()
    cached = CachingEmbeddingProvider(inner)
    assert await cached.embed([]) == []
    assert inner.calls == []


async def test_cached_vectors_are_copies():
    inner = FakeEmbeddingProvider()
    cached = CachingEmbeddingProvider(inner)
    first = await cached.embed(["alpha"])
    first[0][0] = 99.0
    second = await cached.embed(["alpha"])
    assert second[0][0] != 99.0


def test_cache_delegates_identity():
    inner = FakeEmbeddingProvider()
    cached = CachingEmbeddingProvider(inner)
    assert cached.provider_id == inner.provider_id
    assert cached.model == inner.model
    assert cached.dimension == inner.dimension


async def test_distinct_uncached_texts_embed_concurrently():
    inner = _GateProvider()
    cached = CachingEmbeddingProvider(inner)
    first = asyncio.create_task(cached.embed(["alpha"]))
    await inner.started.wait()
    inner.started.clear()
    second = asyncio.create_task(cached.embed(["beta"]))
    await inner.started.wait()
    assert inner.max_in_flight == 2
    inner.release.set()
    assert await first == [[5.0]]
    assert await second == [[4.0]]


async def test_same_text_inflight_shares_one_inner_call():
    inner = _GateProvider()
    cached = CachingEmbeddingProvider(inner)
    first = asyncio.create_task(cached.embed(["alpha"]))
    await inner.started.wait()
    second = asyncio.create_task(cached.embed(["alpha"]))
    await asyncio.sleep(0)
    inner.release.set()
    assert await first == await second == [[5.0]]
    assert inner.calls == 1
