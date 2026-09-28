"""CachingEmbeddingProvider hits memory after the first embed."""

from __future__ import annotations

from app.services.knowledge.embeddings import CachingEmbeddingProvider
from tests.knowledge_fakes import FakeEmbeddingProvider


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
