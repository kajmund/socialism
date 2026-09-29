"""Regression coverage for Graph v2 identity, provenance and traversal."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.graph_v2 import GraphFact, GraphFactRelation, GraphFactSource, GraphNode
from app.database.models import Kund
from app.services.graph_v2.retrieval import hybrid_facts, neighbourhood
from app.services.graph_v2.temporal import invalidate_fact
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.scope import customer_scope


class Judge:
    async def compare(self, proposed, candidate_text):
        if "inte" in proposed.fact_text:
            return "CONTRADICTS"
        if "equivalent" in proposed.fact_text:
            return "SAME"
        return "DISTINCT"


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all([
            Kund(id=1, name="One", slug="one", available_modules=[]),
            Kund(id=2, name="Two", slug="two", available_modules=[]),
        ])
        await db.flush()
        yield db
    await engine.dispose()


async def node(session, label, *, customer=1, context=""):
    return await resolve_node(session, NodeInput(
        node_type="core.concept", name=label, scope=customer_scope(customer),
        context_key=context,
    ))


def fact(source, target, text, *, customer=1, context=None, occurrence="", ref="episode-1"):
    return FactInput(
        source_id=source.id, target_id=target.id, scope=customer_scope(customer),
        predicate="core.relates_to", fact_text=text, context_id=context,
        occurrence_key=occurrence, sources=(SourceRef("episode", ref),),
        embedding=(1.0, 0.0), embedding_model="test",
    )


async def test_same_fact_multiple_sources_semantics_and_contradiction(session):
    a, b = await node(session, "A"), await node(session, "B")
    first, _ = await resolve_fact(session, fact(a, b, "A gäller B"))
    repeated, decision = await resolve_fact(session, fact(a, b, "A gäller B", ref="episode-2"))
    assert first.id == repeated.id and decision == "SAME"
    semantic, decision = await resolve_fact(
        session, fact(a, b, "A är equivalent med B", ref="episode-3"), judge=Judge(),
    )
    assert semantic.id == first.id and decision == "SAME"
    assert await session.scalar(select(func.count()).select_from(GraphFactSource)) == 3
    opposite, decision = await resolve_fact(
        session, fact(a, b, "A gäller inte B", ref="episode-4"), judge=Judge(),
    )
    assert opposite.id != first.id and decision == "CONTRADICTS"
    assert first.invalid_at is None and first.status == "active"
    assert await session.scalar(select(func.count()).select_from(GraphFactRelation)) == 1
    with pytest.raises(ValueError, match="matching scope"):
        other_context = await node(session, "Other context")
        scoped, _ = await resolve_fact(session, fact(a, b, "A gäller inte B", context=other_context.id))
        await invalidate_fact(
            session, prior_id=first.id, successor_id=scoped.id, at=datetime.now(UTC),
        )
    await invalidate_fact(
        session, prior_id=first.id, successor_id=opposite.id, at=datetime.now(UTC),
    )
    assert first.status == "invalidated"


async def test_context_occurrence_tenant_and_multi_hop(session):
    a, b, c = [await node(session, label) for label in ("A", "B", "C")]
    context1, context2 = await node(session, "Case 1"), await node(session, "Case 2")
    first, _ = await resolve_fact(session, fact(a, b, "Samma text", context=context1.id))
    separate, _ = await resolve_fact(session, fact(a, b, "Samma text", context=context2.id))
    historical, _ = await resolve_fact(session, fact(a, b, "Samma text", context=context1.id, occurrence="2024"))
    next_fact, _ = await resolve_fact(session, fact(b, c, "B leder till C"))
    assert len({first.id, separate.id, historical.id}) == 3
    reached = await neighbourhood(session, customer_id=1, seeds=[a.id], max_hops=2)
    assert next_fact.id in {hit.fact.id for hit in reached}
    assert (await hybrid_facts(session, customer_id=1, query="leder C"))[0].fact.id == next_fact.id
    assert await hybrid_facts(session, customer_id=2, query="leder C") == []
    with pytest.raises(ValueError, match="scope"):
        await resolve_fact(session, fact(a, await node(session, "foreign", customer=2), "bad"))


async def test_parallel_repeated_ingest_is_bounded(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/graph.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        await session.commit()

    async def ingest(index):
        async with factory() as session:
            a, b = await node(session, "A"), await node(session, "B")
            await resolve_fact(session, fact(a, b, "A gäller B", ref=f"episode-{index}"))
            await session.commit()

    # SQLite serializes writes; the same nested-transaction conflict path runs on Postgres.
    await asyncio.gather(*(ingest(i) for i in range(3)))
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(GraphNode)) == 2
        assert await session.scalar(select(func.count()).select_from(GraphFact)) == 1
        assert await session.scalar(select(func.count()).select_from(GraphFactSource)) == 3
    await engine.dispose()
