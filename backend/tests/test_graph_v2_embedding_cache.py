"""Embedding cache keys contain representation identity, never tenant identity."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphEmbeddingCache, GraphNode
from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider


class CountingEmbedder:
    provider_id = "fake"
    model = "test-model"
    dimension = 3
    model_revision = "revision-a"

    def __init__(self):
        self.batches: list[list[str]] = []

    async def embed(self, texts):
        self.batches.append(list(texts))
        return [[float(len(text)), *([0.0] * (self.dimension - 1))] for text in texts]


async def test_content_addressed_cache_batches_misses_and_reuses_across_instances(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/embedding-cache.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = CountingEmbedder()

    first = GraphEmbeddingCacheProvider(factory, provider)
    vectors = await first.embed(["  Same   fact. ", "another fact", "  Same   fact. "])
    assert vectors[0] == vectors[2]
    assert provider.batches == [["  Same   fact. ", "another fact"]]

    # A fresh provider (and thus no process-local state) reads the durable vector.
    second = GraphEmbeddingCacheProvider(factory, provider)
    assert await second.embed(["  Same   fact. "]) == [vectors[0]]
    assert provider.batches == [["  Same   fact. ", "another fact"]]
    async with factory() as session:
        rows = list((await session.scalars(select(GraphEmbeddingCache))).all())
        assert len(rows) == 2
        assert all(row.status == "ready" and row.vector for row in rows)
        assert "tenant_id" not in GraphEmbeddingCache.__table__.columns
        assert "normalized_text" not in GraphEmbeddingCache.__table__.columns
    await engine.dispose()


async def test_cache_identity_changes_with_model_revision_dimension_and_purpose(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/embedding-identity.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    embedder = CountingEmbedder()
    await GraphEmbeddingCacheProvider(factory, embedder, purpose="fact.v1").embed(["A fact"])
    revised = CountingEmbedder()
    revised.model_revision = "revision-b"
    await GraphEmbeddingCacheProvider(factory, revised, purpose="fact.v1").embed(["A fact"])
    await GraphEmbeddingCacheProvider(factory, embedder, purpose="question.v1").embed(["A fact"])
    different_dimension = CountingEmbedder()
    different_dimension.dimension = 4
    await GraphEmbeddingCacheProvider(factory, different_dimension, purpose="fact.v1").embed(
        ["A fact"]
    )
    different_model = CountingEmbedder()
    different_model.model = "another-model"
    await GraphEmbeddingCacheProvider(factory, different_model, purpose="fact.v1").embed(["A fact"])
    async with factory() as session:
        rows = list((await session.scalars(select(GraphEmbeddingCache))).all())
        assert len(rows) == 5
    await engine.dispose()


async def test_concurrent_cache_misses_use_one_provider_batch(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/embedding-flight.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class SlowEmbedder(CountingEmbedder):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts):
            self.batches.append(list(texts))
            self.started.set()
            await self.release.wait()
            return [[1.0, 0.0, 0.0] for _ in texts]

    inner = SlowEmbedder()
    cache = GraphEmbeddingCacheProvider(factory, inner)
    leader = asyncio.create_task(cache.embed(["Shared text"]))
    await inner.started.wait()
    follower = asyncio.create_task(cache.embed(["Shared text"]))
    await asyncio.sleep(0.01)
    inner.release.set()
    assert await leader == await follower
    assert inner.batches == [["Shared text"]]
    await engine.dispose()


async def test_cancelling_a_waiter_does_not_cancel_the_shared_embedding(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/embedding-cancel.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class SlowEmbedder(CountingEmbedder):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts):
            self.batches.append(list(texts))
            self.started.set()
            await self.release.wait()
            return [[1.0, 0.0, 0.0] for _ in texts]

    inner = SlowEmbedder()
    cache = GraphEmbeddingCacheProvider(factory, inner)
    owner = asyncio.create_task(cache.embed(["A fact"]))
    await inner.started.wait()
    waiter = asyncio.create_task(cache.embed(["A fact"]))
    await asyncio.sleep(0.01)
    waiter.cancel()
    try:
        await waiter
    except asyncio.CancelledError:
        pass
    inner.release.set()
    assert await owner == [[1.0, 0.0, 0.0]]
    assert inner.batches == [["A fact"]]
    await engine.dispose()


async def test_independent_workers_share_a_content_lease(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/embedding-workers.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class SlowEmbedder(CountingEmbedder):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts):
            self.batches.append(list(texts))
            self.started.set()
            await self.release.wait()
            return [[2.0, 0.0, 0.0] for _ in texts]

    first_provider = SlowEmbedder()
    second_provider = CountingEmbedder()
    first = GraphEmbeddingCacheProvider(factory, first_provider)
    second = GraphEmbeddingCacheProvider(factory, second_provider)
    leader = asyncio.create_task(first.embed(["A shared representation"]))
    await first_provider.started.wait()
    follower = asyncio.create_task(second.embed(["A shared representation"]))
    await asyncio.sleep(0.1)
    first_provider.release.set()
    leader_vector, follower_vector = await asyncio.gather(leader, follower)
    assert leader_vector == follower_vector
    assert first_provider.batches == [["A shared representation"]]
    assert second_provider.batches == []
    await engine.dispose()


async def test_sqlite_projection_can_fill_cache_in_its_write_transaction(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/embedding-transaction.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    inner = CountingEmbedder()
    cache = GraphEmbeddingCacheProvider(factory, inner)
    async with factory.begin() as session:
        session.add(
            GraphNode(
                id="node",
                scope_key="shared",
                customer_id=None,
                node_type="core.concept",
                identity_key="weak::node",
                name="Node",
                normalized_name="node",
                attributes={},
            )
        )
        await session.flush()
        result = await cache.embed_in_session(session, ["A fact"])
        assert len(result) == 1
    async with factory() as session:
        row = await session.scalar(select(GraphEmbeddingCache))
        assert row is not None and row.status == "ready"
    assert inner.batches == [["A fact"]]
    await engine.dispose()
