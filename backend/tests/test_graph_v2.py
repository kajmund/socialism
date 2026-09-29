"""Regression coverage for Graph v2 identity, provenance and traversal."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.graph_v2 import (
    GraphFact, GraphFactQuestionDependency, GraphFactRelation, GraphFactRevalidation,
    GraphFactSource, GraphNode,
)
from app.database.models import Kund
from app.services.graph_v2.retrieval import hybrid_facts, neighbourhood
from app.services.graph_v2.revalidation import (
    attach_question_dependency,
    enqueue_question_revalidation,
    process_question_revalidation_work,
)
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
    class OppositeFirst:
        async def compare(self, proposed, candidate_text):
            return "CONTRADICTS" if "inte" in candidate_text else "SAME"

    opposite.embedding = [0.0, 1.0]
    matching, decision = await resolve_fact(
        session,
        replace(fact(a, b, "A gäller också B", ref="episode-5"), embedding=(0.0, 1.0)),
        judge=OppositeFirst(),
    )
    assert matching.id == first.id and decision == "SAME"
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


async def test_weak_node_judge_can_merge_synonyms_only_within_context(session):
    class SynonymJudge:
        async def same_node(self, proposed, candidate_name):
            return proposed.name == "automobile" and candidate_name == "car"

    first = await node(session, "car", context="case-1")
    same = await resolve_node(session, NodeInput(
        node_type="core.concept", name="automobile", scope=customer_scope(1),
        context_key="case-1",
    ), judge=SynonymJudge())
    separate = await node(session, "car", context="case-2")
    assert first.id == same.id and first.id != separate.id


async def test_graph_revalidation_is_fact_provenance_and_question_scoped(session):
    subject, target = await node(session, "Case X"), await node(session, "Outcome")
    question = await resolve_node(session, NodeInput(
        node_type="core.question", name="Can the outcome be changed?",
        scope=customer_scope(1), identifier_namespace="research.question_id",
        identifier="question-1",
    ))
    original, _ = await resolve_fact(session, fact(subject, target, "No adjustment", ref="unit-1"))

    class Distinct:
        async def compare(self, proposed, candidate_text):
            return "DISTINCT"

    changed, _ = await resolve_fact(
        session, fact(subject, target, "Adjustment granted", ref="unit-2"), judge=Distinct(),
    )
    changed.created_at = original.created_at + timedelta(seconds=1)
    await enqueue_question_revalidation(
        session, customer_id=1, question_node_id=question.id, evidence_set_id="frozen-set-1",
    )
    assert await process_question_revalidation_work(session) == {"completed": 0, "waiting": 1}
    dependency = await attach_question_dependency(
        session, question_node_id=question.id, fact_id=original.id,
    )
    assert dependency.provenance == [{"kind": "episode", "ref": "unit-1"}]
    await resolve_fact(session, fact(subject, target, "No adjustment", ref="unit-3"))
    dependency = await attach_question_dependency(
        session, question_node_id=question.id, fact_id=original.id,
    )
    assert dependency.provenance == [
        {"kind": "episode", "ref": "unit-1"},
        {"kind": "episode", "ref": "unit-3"},
    ]
    await attach_question_dependency(session, question_node_id=question.id, fact_id=changed.id)
    assert await process_question_revalidation_work(session) == {"completed": 1, "waiting": 0}
    pending = list((await session.scalars(select(GraphFactRevalidation))).all())
    assert len(pending) == 1
    assert pending[0].question_node_id == question.id
    assert pending[0].trigger_fact_id == changed.id
    assert pending[0].dependent_fact_id == original.id
    assert pending[0].trigger_provenance == [{"kind": "episode", "ref": "unit-2"}]
    assert pending[0].dependent_provenance == [
        {"kind": "episode", "ref": "unit-1"},
        {"kind": "episode", "ref": "unit-3"},
    ]
    assert await process_question_revalidation_work(session) == {"completed": 0, "waiting": 0}
    assert await session.scalar(select(func.count()).select_from(GraphFactQuestionDependency)) == 2


def test_legacy_event_revalidation_is_not_public_knowledge_api():
    import app.services.knowledge as knowledge

    assert not hasattr(knowledge, "revalidate_after_event")
    assert not hasattr(knowledge, "revalidate_after_events")


async def test_hybrid_embedding_model_boundary(session):
    a, b = await node(session, "A"), await node(session, "B")
    await resolve_fact(session, fact(a, b, "unrelated words"))
    assert len(await hybrid_facts(
        session, customer_id=1, query="absent", embedding=[1.0, 0.0],
        embedding_model="test",
    )) == 1
    assert await hybrid_facts(
        session, customer_id=1, query="absent", embedding=[1.0, 0.0],
        embedding_model="other",
    ) == []


async def test_cross_domain_traversal_over_shared_context(session):
    legal = await resolve_node(session, NodeInput(
        node_type="legal.contract", name="Agreement 42", scope=customer_scope(1),
        identifier_namespace="legal.contract_id", identifier="42",
    ))
    company = await resolve_node(session, NodeInput(
        node_type="finance.company", name="AB Example", scope=customer_scope(1),
        identifier_namespace="finance.org_number", identifier="556000-0000",
    ))
    context = await node(session, "Case 42")
    first, _ = await resolve_fact(session, fact(legal, context, "Avtalet hör till ärendet"))
    second, _ = await resolve_fact(session, fact(context, company, "Ärendet avser bolaget"))
    hits = await neighbourhood(session, customer_id=1, seeds=[legal.id], max_hops=2)
    assert {first.id, second.id} <= {hit.fact.id for hit in hits}


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

            class DuplicateJudge:
                async def compare(self, proposed, candidate_text):
                    return "SAME" if proposed.fact_text == candidate_text else "DISTINCT"

            await resolve_fact(
                session, fact(a, b, "A gäller B", ref=f"episode-{index}"),
                judge=DuplicateJudge(),
            )
            await session.commit()

    # SQLite serializes writes; the same nested-transaction conflict path runs on Postgres.
    await asyncio.gather(*(ingest(i) for i in range(3)))
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(GraphNode)) == 2
        assert await session.scalar(select(func.count()).select_from(GraphFact)) == 1
        assert await session.scalar(select(func.count()).select_from(GraphFactSource)) == 3
    await engine.dispose()
