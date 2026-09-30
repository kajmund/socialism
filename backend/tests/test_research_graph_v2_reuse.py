"""Exercise the graph-only research read path with real persisted provenance."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.graph_v2 import GraphFact, GraphFactQuestionDependency, GraphFactSource, GraphNode
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund, TextUnitRecord
from app.services.knowledge.models import KnowledgeScope
from app.services.research.graph_grounding import GraphResearchError
from app.services.research.graph_reuse import GraphQueryEmbedding, lookup_graph_evidence as read_graph_evidence
from app.services.research.models import ResearchContext, ResearchNeed

NOW = datetime.now(UTC)


class Embeddings:
    model = "test-graph-embedding"
    dimension = 3
    provider_id = "test"

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


async def lookup_graph_evidence(session, **kwargs):
    """Hydration tests supply a precomputed vector; only the wrapper calls embeddings."""
    kwargs.setdefault("query_embedding", GraphQueryEmbedding(Embeddings.model, 3, [1.0, 0.0, 0.0]))
    return await read_graph_evidence(session, **kwargs)


@pytest.fixture
async def graph_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr("app.services.research.composition.research_embeddings", Embeddings)
    async with factory() as session:
        session.add_all(
            [Kund(id=1, name="First", slug="first"), Kund(id=2, name="Second", slug="second")]
        )
        await session.flush()
        yield session
    await engine.dispose()


def need() -> ResearchNeed:
    return ResearchNeed(
        id="need_6",
        question="36 § avtalslagen senare lagändringar",
        why_needed="Förarbetsuttalanden",
        source_types=["swedish_preparatory_works"],
    )


def context(customer_id=1, *, case_id=None, module="dd") -> ResearchContext:
    return ResearchContext(
        scope=KnowledgeScope(customer_id=customer_id, case_id=case_id, module=module)
    )


async def seed_fact(
    session: AsyncSession,
    *,
    scope="customer:1",
    source_scope=None,
    attributes=None,
    source_extra=None,
) -> GraphFact:
    customer_id = int(scope.split(":")[1]) if scope != "shared" else None
    source_scope = source_scope or scope
    source_customer = int(source_scope.split(":")[1]) if source_scope != "shared" else None
    source_fields = dict(
        scope_type="shared" if source_scope == "shared" else "customer",
        scope_key=source_scope,
        customer_id=source_customer,
    )
    suffix = scope.replace(":", "-")
    document = CanonicalDocumentRecord(
        id=f"doc-{suffix}",
        canonical_uri="https://lagen.nu/prop/1994/95:17",
        title="Prop. 1994/95:17",
        source_type="swedish_preparatory_works",
        extra=source_extra or {},
        **source_fields,
    )
    session.add(document)
    await session.flush()
    version = DocumentVersionRecord(
        id=f"version-{suffix}",
        document_id=document.id,
        mime_type="text/plain",
        content_hash="version-hash",
        ingested_at=NOW,
        **source_fields,
    )
    session.add(version)
    await session.flush()
    unit = TextUnitRecord(
        id=f"unit-{suffix}",
        document_id=document.id,
        document_version_id=version.id,
        ordinal=0,
        text="36 § avtalslagen senare lagändringar i förarbetena.",
        content_hash="unit-hash",
        locator="a4.2",
        ingested_at=NOW,
        **source_fields,
    )
    nodes = [
        GraphNode(
            id=f"source-{suffix}",
            scope_key=scope,
            customer_id=customer_id,
            node_type="legal.source",
            identity_key="source",
            name="Avtalslagen",
            normalized_name="avtalslagen",
        ),
        GraphNode(
            id=f"target-{suffix}",
            scope_key=scope,
            customer_id=customer_id,
            node_type="legal.value",
            identity_key="value",
            name="Lagändringar",
            normalized_name="lagändringar",
        ),
    ]
    session.add_all([unit, *nodes])
    await session.flush()
    fact = GraphFact(
        id=f"fact-{suffix}",
        identity_key=f"identity-{suffix}",
        scope_key=scope,
        customer_id=customer_id,
        source_id=nodes[0].id,
        target_id=nodes[1].id,
        predicate="legal.legislative_intent",
        fact_text=unit.text,
        normalized_text=unit.text.casefold(),
        status="active",
        embedding=[1.0, 0.0, 0.0],
        embedding_model=Embeddings.model,
        attributes=attributes or {},
    )
    session.add(fact)
    await session.flush()
    session.add(GraphFactSource(fact_id=fact.id, source_kind="text_unit", source_ref=unit.id))
    await session.flush()
    return fact


async def test_graph_fact_is_hydrated_without_claims_and_keeps_source_ids(graph_db):
    fact = await seed_fact(graph_db)
    hits = await lookup_graph_evidence(graph_db, need=need(), context=context(), now=NOW)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.provider == "graph_v2"
    assert hit.research_need_id == "need_6"
    assert hit.locator == "a4.2"
    assert hit.source_url == "https://lagen.nu/prop/1994/95:17"
    assert hit.metadata["graph_fact_ids"] == [fact.id]
    assert hit.metadata["supporting_text_unit_ids"] == ["unit-customer-1"]
    assert hit.metadata["document_version_id"] == "version-customer-1"
    assert "knowledge_claim_ids" not in hit.metadata


async def test_empty_graph_requires_no_query_embedding(graph_db):
    assert await read_graph_evidence(graph_db, need=need(), context=context()) == []


async def test_canonical_dependency_is_read_from_graph_without_legacy_links(graph_db, monkeypatch):
    fact = await seed_fact(graph_db)
    question_node = GraphNode(
        id="question-node",
        scope_key="customer:1",
        customer_id=1,
        node_type="research.question",
        identity_key="canonical-36",
        name=need().question,
        normalized_name=need().question,
        attributes={"canonical_question_id": "canonical-36"},
    )
    graph_db.add(question_node)
    await graph_db.flush()
    graph_db.add(
        GraphFactQuestionDependency(
            id="question-dependency",
            scope_key="customer:1",
            question_node_id=question_node.id,
            fact_id=fact.id,
        )
    )
    await graph_db.flush()
    monkeypatch.setattr(
        "app.services.research.graph_reuse.hybrid_facts", AsyncMock(return_value=[])
    )
    current_need = replace(need(), knowledge_question_id="canonical-36")
    hits = await lookup_graph_evidence(graph_db, need=current_need, context=context())
    assert [item.metadata["graph_fact_ids"] for item in hits] == [[fact.id]]
    assert await lookup_graph_evidence(graph_db, need=current_need, context=context(2)) == []


async def test_graph_evidence_bound_is_enforced(graph_db):
    await seed_fact(graph_db)
    await seed_fact(graph_db, scope="shared")
    assert len(await lookup_graph_evidence(graph_db, need=need(), context=context(), limit=1)) == 1
    with pytest.raises(ValueError, match="positive"):
        await lookup_graph_evidence(graph_db, need=need(), context=context(), limit=0)


async def test_customer_and_shared_visibility(graph_db):
    private = await seed_fact(graph_db)
    shared = await seed_fact(graph_db, scope="shared")
    first = await lookup_graph_evidence(graph_db, need=need(), context=context())
    second = await lookup_graph_evidence(graph_db, need=need(), context=context(2))
    assert {hit.metadata["graph_fact_ids"][0] for hit in first} == {private.id, shared.id}
    assert {hit.metadata["graph_fact_ids"][0] for hit in second} == {shared.id}


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "invalidated"),
        ("valid_at", NOW + timedelta(days=1)),
        ("invalid_at", NOW - timedelta(days=1)),
    ],
)
async def test_invalid_or_future_facts_are_not_reused(graph_db, field, value):
    fact = await seed_fact(graph_db)
    setattr(fact, field, value)
    await graph_db.flush()
    assert await lookup_graph_evidence(graph_db, need=need(), context=context(), now=NOW) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("superseded_at", NOW),
        ("valid_from", NOW + timedelta(days=1)),
        ("valid_to", NOW - timedelta(days=1)),
    ],
)
async def test_source_version_must_be_current(graph_db, field, value):
    await seed_fact(graph_db)
    version = await graph_db.get(DocumentVersionRecord, "version-customer-1")
    setattr(version, field, value)
    await graph_db.flush()
    assert await lookup_graph_evidence(graph_db, need=need(), context=context(), now=NOW) == []


async def test_case_source_requires_matching_document_scope(graph_db):
    await seed_fact(graph_db, source_extra={"knowledge_case_id": "case-1"})
    document = await graph_db.get(CanonicalDocumentRecord, "doc-customer-1")
    document.source_type = "case_knowledge"
    await graph_db.flush()
    case_need = ResearchNeed(
        id="case-need",
        question=need().question,
        why_needed="Case context",
        source_types=["case_knowledge"],
    )
    assert await lookup_graph_evidence(graph_db, need=case_need, context=context()) == []
    hits = await lookup_graph_evidence(graph_db, need=case_need, context=context(case_id="case-1"))
    assert len(hits) == 1
    document.extra = {}
    await graph_db.flush()
    assert (
        await lookup_graph_evidence(graph_db, need=case_need, context=context(case_id="case-1"))
        == []
    )


async def test_reuse_keeps_source_age_and_does_not_refresh_it(graph_db, monkeypatch):
    from app.config import settings

    await seed_fact(graph_db)
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 60)
    hits = await lookup_graph_evidence(
        graph_db, need=need(), context=context(), now=NOW + timedelta(seconds=61)
    )
    assert hits[0].metadata["reuse"]["freshness"] == "stale"
    assert hits[0].retrieved_at == NOW
    version = await graph_db.get(DocumentVersionRecord, "version-customer-1")
    assert version.ingested_at.replace(tzinfo=UTC) == NOW


async def test_wrong_case_or_module_is_not_reused(graph_db):
    await seed_fact(
        graph_db, source_extra={"knowledge_case_id": "case-1", "knowledge_module": "dd"}
    )
    assert await lookup_graph_evidence(graph_db, need=need(), context=context()) == []
    assert (
        await lookup_graph_evidence(graph_db, need=need(), context=context(case_id="case-2")) == []
    )
    assert (
        await lookup_graph_evidence(
            graph_db, need=need(), context=context(case_id="case-1", module="politik")
        )
        == []
    )
    assert (
        len(await lookup_graph_evidence(graph_db, need=need(), context=context(case_id="case-1")))
        == 1
    )


async def test_shared_fact_cannot_expose_private_sources(graph_db):
    await seed_fact(graph_db, scope="shared", source_scope="customer:1")
    with pytest.raises(GraphResearchError, match="source scope"):
        await lookup_graph_evidence(graph_db, need=need(), context=context(2))


async def test_broken_text_unit_ref_fails_loudly(graph_db):
    fact = await seed_fact(graph_db)
    graph_db.add(
        GraphFactSource(fact_id=fact.id, source_kind="text_unit", source_ref="missing-unit")
    )
    await graph_db.flush()
    with pytest.raises(GraphResearchError, match="missing supporting"):
        await lookup_graph_evidence(graph_db, need=need(), context=context())


async def test_graph_read_refuses_to_embed_inside_a_database_transaction(graph_db):
    await seed_fact(graph_db)
    with pytest.raises(GraphResearchError, match="Prepare query embedding"):
        await read_graph_evidence(graph_db, need=need(), context=context())


async def test_missing_customer_fails_closed(graph_db):
    from app.services.knowledge.models import KnowledgeScopeRequiredError

    with pytest.raises(KnowledgeScopeRequiredError, match="customer_id"):
        await lookup_graph_evidence(
            graph_db,
            need=need(),
            context=ResearchContext(scope=KnowledgeScope(scope_type="shared")),
        )


async def _attempt(session):
    from app.services.execution import create_attempt, create_run

    run = await create_run(session, customer_id=1, module="dd", title="Graph retrieval", context={})
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={},
        input_snapshot={},
    )
    await session.commit()
    return attempt


async def test_attempt_skips_live_sources_after_sufficient_graph_assessment(graph_db):
    from app.services.execution import get_evidence_set, list_evidence_items
    from app.services.research import ResearchPlan, execute_attempt_research
    from tests.test_research_question_evidence import RecordingSource, _router

    await seed_fact(graph_db)
    attempt = await _attempt(graph_db)
    source = RecordingSource("swedish_preparatory_works", excerpt="Extern komplettering")
    result = await execute_attempt_research(
        graph_db,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[need()]),
        router=_router(source)[0],
    )
    items = await list_evidence_items(graph_db, result.evidence_set_id)
    assert source.calls == 0
    assert {item.provider for item in items} == {"graph_v2"}
    graph_item = next(item for item in items if item.provider == "graph_v2")
    assert graph_item.provenance["graph_fact_ids"] == ["fact-customer-1"]
    frozen = await get_evidence_set(graph_db, result.evidence_set_id)
    assert frozen.grounded_refs["graph_fact_ids"] == ["fact-customer-1"]
    assert "version-customer-1" in frozen.grounded_refs["document_version_ids"]
    assert "unit-customer-1" in frozen.grounded_refs["text_unit_ids"]
    assert result.status == "ready"


async def test_graph_read_failure_marks_attempt_and_need_failed_without_external_search(
    graph_db, monkeypatch
):
    from app.services.execution import get_attempt, list_need_executions
    from app.services.research import ResearchPlan, execute_attempt_research
    from app.services.research.execution import ResearchExecutionError
    from tests.test_research_question_evidence import RecordingSource, _router

    attempt = await _attempt(graph_db)
    monkeypatch.setattr(
        "app.services.research.graph_reuse._candidates",
        AsyncMock(side_effect=RuntimeError("Graph database unavailable")),
    )
    source = RecordingSource("swedish_preparatory_works")
    with pytest.raises(ResearchExecutionError):
        await execute_attempt_research(
            graph_db,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[need()]),
            router=_router(source)[0],
        )
    assert source.calls == 0
    assert (await get_attempt(graph_db, attempt.id)).status == "failed"
    assert {row.status for row in await list_need_executions(graph_db, attempt.id)} == {"failed"}


async def test_expert_chat_reads_graph_evidence_only_after_freeze(graph_db):
    from app.services.execution import add_evidence_items
    from app.services.execution.service import (
        attach_evidence_set,
        create_evidence_set,
        freeze_evidence_set,
        mark_ready,
    )
    from app.services.expert_chat_evidence import reusable_expert_chat_evidence_context

    await seed_fact(graph_db)
    hits = await lookup_graph_evidence(graph_db, need=need(), context=context())
    attempt = await _attempt(graph_db)
    evidence_set = await create_evidence_set(
        graph_db, run_id=attempt.run_id, created_from_attempt_id=attempt.id
    )
    await attach_evidence_set(graph_db, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    await add_evidence_items(graph_db, evidence_set_id=evidence_set.id, items=hits)
    args = dict(
        customer_id=1,
        question=need().question,
        prompts={"chat.expert.research_evidence": "FRYST EVIDENS\n{evidence}"},
    )
    await graph_db.commit()
    assert await reusable_expert_chat_evidence_context(graph_db, **args) == ""
    await freeze_evidence_set(graph_db, evidence_set.id)
    await mark_ready(graph_db, attempt.id)
    await graph_db.commit()
    rendered = await reusable_expert_chat_evidence_context(graph_db, **args)
    assert "FRYST EVIDENS" in rendered
    assert "Prop. 1994/95:17" in rendered
    assert "a4.2" in rendered
