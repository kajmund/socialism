"""Hard tenant boundary: customer knowledge never leaks into shared or other tenants."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    EvidenceSetRevalidation,
    KnowledgeClaimAnswer,
    KnowledgeClaimRecord,
    KnowledgeEntityRecord,
    KnowledgeGraphEventRecord,
    KnowledgeQuestionRow,
    Kund,
    TextUnitRecord,
)
from app.services.execution.service import (
    add_evidence_items,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
)
from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.claims import (
    KnowledgeClaim,
    KnowledgeClaimError,
    answer_research_need,
    claim_answers_for_question_key,
    knowledge_claim_id,
    persist_knowledge_claim,
)
from app.services.knowledge.entities import (
    KnowledgeEntityError,
    knowledge_entity,
    lookup_knowledge_entity,
    lookup_readable_entity,
    persist_knowledge_entity,
)
from app.services.knowledge.events import list_graph_events
from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    EmbeddedKnowledgeQuery,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeQuery,
    KnowledgeScope,
    KnowledgeScopeRequiredError,
)
from app.services.knowledge.persistence import (
    get_canonical_document_by_identity,
    persist_segmented_document,
)
from app.services.knowledge.relationships import (
    ABOUT,
    SAME_AS,
    KnowledgeRelationshipError,
    knowledge_relationship,
    persist_knowledge_relationship,
    relationships_touching,
)
from app.services.knowledge.revalidation import (
    GraphImpact,
    affected_frozen_evidence_sets,
    graph_impact_from_event,
)
from app.services.knowledge.scope import (
    SCOPE_SHARED,
    KnowledgeScopeError,
    require_persist_scope,
    shared_scope,
)
from app.services.knowledge.segmentation import DocumentSegmenter
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.research.knowledge_question import (
    identity_from_text,
    public_question_scope,
    tenant_question_scope,
)
from app.services.research.models import research_evidence
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.question_iteration import (
    match_canonical_question,
    resolve_or_create_knowledge_question,
)
from app.services.research.question_semantic import SemanticQuestionIdentityMatcher
from tests.knowledge_fakes import FakeEmbeddingProvider, fake_embed_text


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add_all(
            [
                Kund(id=1, name="acme", slug="acme", available_modules=["dd"]),
                Kund(id=2, name="beta", slug="beta", available_modules=["dd"]),
            ]
        )
        await db.flush()
        yield db
    await engine.dispose()


def _document(
    *,
    document_id: str,
    customer_id: int | None,
    title: str,
    scope_type: str = "customer",
    source_type: str = "upload",
    canonical_uri: str | None = None,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        provider="supabase",
        external_id=canonical_uri or document_id,
        title=title,
        mime_type="text/plain",
        scope=KnowledgeScope(
            customer_id=customer_id,
            case_id=None,
            module="dd",
            scope_type=scope_type,
        ),
        source_type=source_type,
        canonical_uri=canonical_uri or f"doc://{document_id}",
    )


def _extracted(text: str) -> ExtractedDocument:
    return ExtractedDocument(
        blocks=[ExtractedBlock(text=text, locator="page:1", metadata={"page": 1})]
    )


async def _persist_doc(
    session: AsyncSession,
    *,
    document_id: str,
    text: str,
    customer_id: int | None = None,
    scope_type: str = "customer",
    source_type: str = "upload",
    canonical_uri: str | None = None,
    title: str = "Doc",
):
    scope = shared_scope() if scope_type == SCOPE_SHARED else None
    document = _document(
        document_id=document_id,
        customer_id=customer_id,
        title=title,
        scope_type=scope_type,
        source_type=source_type,
        canonical_uri=canonical_uri,
    )
    segmented = DocumentSegmenter().segment(
        _extracted(text),
        document,
        content_hash=f"hash-{document_id}",
        source_type=source_type,
        canonical_uri=document.canonical_uri,
    )
    return await persist_segmented_document(
        session,
        customer_id=customer_id,
        scope=scope,
        segmented=segmented,
    )


async def _claim_for_doc(
    session: AsyncSession,
    *,
    persisted,
    customer_id: int | None,
    predicate: str,
    value: dict[str, object],
    scope_type: str = "customer",
) -> KnowledgeClaim:
    units = list(
        (
            await session.execute(
                select(TextUnitRecord).where(
                    TextUnitRecord.document_version_id == persisted.version.id
                )
            )
        ).scalars().all()
    )
    claim = KnowledgeClaim(
        id=knowledge_claim_id(
            document_version_id=persisted.version.id,
            predicate=predicate,
            value=value,
        ),
        customer_id=customer_id,
        scope_type=scope_type,
        document_id=persisted.document.id,
        document_version_id=persisted.version.id,
        predicate=predicate,
        value=value,
        supporting_text_unit_ids=tuple(unit.id for unit in units),
    )
    await persist_knowledge_claim(session, claim)
    return claim


async def test_customer_document_is_not_readable_or_reused_by_other_customer(
    session: AsyncSession,
):
    await _persist_doc(
        session,
        document_id="contract-a",
        customer_id=1,
        text="Customer A secret termination is 90 days.",
        canonical_uri="doc://contract",
    )
    assert (
        await get_canonical_document_by_identity(
            session,
            customer_id=2,
            source_type="upload",
            canonical_uri="doc://contract",
        )
        is None
    )
    other = await _persist_doc(
        session,
        document_id="contract-b",
        customer_id=2,
        text="Customer B public brochure.",
        canonical_uri="doc://contract",
    )
    rows = list((await session.execute(select(CanonicalDocumentRecord))).scalars().all())
    assert {row.customer_id for row in rows} == {1, 2}
    assert other.document.id == "contract-b"
    units = list((await session.execute(select(TextUnitRecord))).scalars().all())
    assert {row.customer_id for row in units} == {1, 2}


async def test_customer_claims_cannot_answer_other_customer_question(
    session: AsyncSession,
):
    persisted = await _persist_doc(
        session,
        document_id="doc-a",
        customer_id=1,
        text="Our contract with Volvo has 90-day termination.",
    )
    claim = await _claim_for_doc(
        session,
        persisted=persisted,
        customer_id=1,
        predicate="contract.termination_days",
        value={"days": 90},
    )
    key = "same-question-key"
    await answer_research_need(
        session,
        research_need_id="need-a",
        question_key=key,
        claim_ids=[claim.id],
        source_type="upload",
    )
    assert await claim_answers_for_question_key(
        session, customer_id=1, question_key=key
    )
    assert (
        await claim_answers_for_question_key(session, customer_id=2, question_key=key)
        == []
    )


async def test_customer_graph_does_not_appear_in_other_customer_traversal(
    session: AsyncSession,
):
    entity_a = knowledge_entity(
        customer_id=1, entity_type="org", key="volvo ab", name="Volvo AB"
    )
    await persist_knowledge_entity(session, entity_a)
    persisted = await _persist_doc(
        session,
        document_id="doc-a",
        customer_id=1,
        text="Our contract with Volvo has 90-day termination.",
    )
    claim = await _claim_for_doc(
        session,
        persisted=persisted,
        customer_id=1,
        predicate="contract.termination_days",
        value={"days": 90},
    )
    await persist_knowledge_relationship(
        session,
        knowledge_relationship(
            customer_id=1,
            relation=ABOUT,
            from_kind="claim",
            from_id=claim.id,
            to_kind="entity",
            to_id=entity_a.id,
        ),
    )
    assert await relationships_touching(
        session, customer_id=2, kind="claim", node_id=claim.id
    ) == []
    assert await relationships_touching(
        session, customer_id=2, kind="entity", node_id=entity_a.id
    ) == []
    assert (
        await lookup_knowledge_entity(
            session, customer_id=2, entity_type="org", key="volvo ab"
        )
        is None
    )


async def test_missing_customer_id_cannot_promote_private_claim_to_global(
    session: AsyncSession,
):
    persisted = await _persist_doc(
        session,
        document_id="doc-a",
        customer_id=1,
        text="Secret rebate is 12 percent.",
    )
    with pytest.raises(KnowledgeScopeError, match="do not infer shared"):
        require_persist_scope(customer_id=None)
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeScope()
    units = list(
        (
            await session.execute(
                select(TextUnitRecord).where(
                    TextUnitRecord.document_id == persisted.document.id
                )
            )
        ).scalars().all()
    )
    with pytest.raises(KnowledgeScopeError):
        KnowledgeClaim(
            id="claim-missing-scope",
            customer_id=None,
            document_id=persisted.document.id,
            document_version_id=persisted.version.id,
            predicate="contract.rebate",
            value={"pct": 12},
            supporting_text_unit_ids=tuple(unit.id for unit in units),
        )
    with pytest.raises(KnowledgeEntityError):
        knowledge_entity(entity_type="org", key="volvo ab", name="Volvo AB")
    shared_volvo = knowledge_entity(
        scope=shared_scope(), entity_type="org", key="volvo ab", name="Volvo AB"
    )
    await persist_knowledge_entity(session, shared_volvo)
    with pytest.raises(KnowledgeClaimError, match="cannot be promoted"):
        await persist_knowledge_claim(
            session,
            KnowledgeClaim(
                id=knowledge_claim_id(
                    document_version_id=persisted.version.id,
                    predicate="contract.rebate",
                    value={"pct": 12},
                ),
                customer_id=None,
                scope_type=SCOPE_SHARED,
                document_id=persisted.document.id,
                document_version_id=persisted.version.id,
                predicate="contract.rebate",
                value={"pct": 12},
                supporting_text_unit_ids=tuple(unit.id for unit in units),
            ),
        )


async def test_shared_claim_and_entity_are_readable_by_both_customers(
    session: AsyncSession,
):
    shared_doc = await _persist_doc(
        session,
        document_id="hd-judgment",
        customer_id=None,
        scope_type=SCOPE_SHARED,
        source_type="lagen_nu",
        canonical_uri="https://lagen.nu/dom/nja/2005s142",
        title="NJA 2005 s. 142",
        text="HD held that the clause was not adjusted.",
    )
    shared_claim = await _claim_for_doc(
        session,
        persisted=shared_doc,
        customer_id=None,
        scope_type=SCOPE_SHARED,
        predicate="legal.adjustment_granted",
        value={"granted": False},
    )
    shared_court = knowledge_entity(
        scope=shared_scope(),
        entity_type="court",
        key="hogsta domstolen",
        name="Högsta domstolen",
    )
    await persist_knowledge_entity(session, shared_court)
    await persist_knowledge_relationship(
        session,
        knowledge_relationship(
            scope=shared_scope(),
            relation=ABOUT,
            from_kind="claim",
            from_id=shared_claim.id,
            to_kind="entity",
            to_id=shared_court.id,
        ),
    )
    key = "hd-question"
    await answer_research_need(
        session,
        research_need_id="need-shared",
        question_key=key,
        claim_ids=[shared_claim.id],
        source_type="swedish_case_law",
    )
    for customer_id in (1, 2):
        hits = await claim_answers_for_question_key(
            session, customer_id=customer_id, question_key=key
        )
        assert [hit.claim.id for hit in hits] == [shared_claim.id]
        assert await lookup_readable_entity(
            session, reader_customer_id=customer_id, entity_type="court", key="hogsta domstolen"
        )
        touching = await relationships_touching(
            session, customer_id=customer_id, kind="entity", node_id=shared_court.id
        )
        assert {edge.relation for edge in touching} == {ABOUT}


async def test_private_claim_may_reference_shared_entity_without_becoming_global(
    session: AsyncSession,
):
    volvo = knowledge_entity(
        scope=shared_scope(), entity_type="org", key="volvo ab", name="Volvo AB"
    )
    await persist_knowledge_entity(session, volvo)
    persisted = await _persist_doc(
        session,
        document_id="contract-a",
        customer_id=1,
        text="Our contract with Volvo has 90-day termination.",
    )
    claim = await _claim_for_doc(
        session,
        persisted=persisted,
        customer_id=1,
        predicate="contract.termination_days",
        value={"days": 90},
    )
    edge = await persist_knowledge_relationship(
        session,
        knowledge_relationship(
            customer_id=1,
            relation=ABOUT,
            from_kind="claim",
            from_id=claim.id,
            to_kind="entity",
            to_id=volvo.id,
        ),
    )
    stored_claim = await session.get(KnowledgeClaimRecord, claim.id)
    assert stored_claim is not None
    assert stored_claim.scope_type == "customer"
    assert stored_claim.customer_id == 1
    assert edge.scope_type == "customer"
    assert edge.customer_id == 1
    assert await session.get(KnowledgeEntityRecord, volvo.id)
    assert (
        await lookup_knowledge_entity(
            session, customer_id=1, entity_type="org", key="volvo ab"
        )
        is None
    )
    assert await relationships_touching(
        session, customer_id=2, kind="claim", node_id=claim.id
    ) == []


async def test_canonical_question_reuse_is_tenant_safe(session: AsyncSession):
    graph = SqlQuestionEvidenceGraph()
    question = "När får avtalet sägas upp?"
    first = await resolve_or_create_knowledge_question(
        session, graph=graph, question=question, scope=tenant_question_scope(1)
    )
    second = await resolve_or_create_knowledge_question(
        session, graph=graph, question=question, scope=tenant_question_scope(1)
    )
    other = await resolve_or_create_knowledge_question(
        session, graph=graph, question=question, scope=tenant_question_scope(2)
    )
    public = await resolve_or_create_knowledge_question(
        session, graph=graph, question=question, scope=public_question_scope()
    )
    assert first.id == second.id
    assert other.id != first.id
    assert public.id != first.id
    assert public.scope.visibility == "public"
    assert (
        await match_canonical_question(session, question, tenant_question_scope(2))
    ).id == other.id
    rows = list((await session.execute(select(KnowledgeQuestionRow))).scalars().all())
    assert {row.customer_id for row in rows} == {1, 2, None}


async def test_canonical_document_identity_is_tenant_safe(session: AsyncSession):
    shared = await _persist_doc(
        session,
        document_id="shared-hd",
        customer_id=None,
        scope_type=SCOPE_SHARED,
        source_type="lagen_nu",
        canonical_uri="https://lagen.nu/dom/nja/2005s142",
        title="NJA 2005 s. 142",
        text="Shared HD judgment.",
    )
    customer = await _persist_doc(
        session,
        document_id="customer-hd-copy",
        customer_id=1,
        source_type="lagen_nu",
        canonical_uri="https://lagen.nu/dom/nja/2005s142",
        title="Customer copy",
        text="Customer-local ingest of the same URI.",
    )
    other = await _persist_doc(
        session,
        document_id="customer-b-hd",
        customer_id=2,
        source_type="lagen_nu",
        canonical_uri="https://lagen.nu/dom/nja/2005s142",
        title="Other copy",
        text="Customer B ingest.",
    )
    assert shared.document.id != customer.document.id
    assert customer.document.id != other.document.id
    assert shared.document.scope_type == SCOPE_SHARED
    assert customer.document.customer_id == 1
    assert other.document.customer_id == 2


async def test_semantic_and_entity_resolution_cannot_merge_tenants(
    session: AsyncSession,
):
    first = knowledge_entity(
        customer_id=1, entity_type="org", key="volvo ab", name="Volvo AB"
    )
    second = knowledge_entity(
        customer_id=2, entity_type="org", key="volvo ab", name="Volvo AB"
    )
    await persist_knowledge_entity(session, first)
    await persist_knowledge_entity(session, second)
    assert first.id != second.id
    with pytest.raises(KnowledgeRelationshipError, match="SAME_AS"):
        await persist_knowledge_relationship(
            session,
            knowledge_relationship(
                customer_id=1,
                relation=SAME_AS,
                from_kind="entity",
                from_id=first.id,
                to_kind="entity",
                to_id=second.id,
            ),
        )
    store = MemoryKnowledgeVectorStore()
    graph = SqlQuestionEvidenceGraph(
        matcher=SemanticQuestionIdentityMatcher(
            vector_store=store,
            embeddings=FakeEmbeddingProvider(),
            version="test-v1",
            threshold=0.1,
            limit=5,
        )
    )
    await resolve_or_create_knowledge_question(
        session,
        graph=graph,
        question="När får avtalet jämkas?",
        scope=tenant_question_scope(1),
    )
    match = await graph.match_question(
        session,
        identity_from_text("När kan avtalet jämkas?"),
        tenant_question_scope(2),
    )
    assert match is None


async def test_revalidation_only_finds_evidence_sets_in_tenant_scope(
    session: AsyncSession,
):
    persisted = await _persist_doc(
        session,
        document_id="doc-a",
        customer_id=1,
        text="HD ansåg att villkoret inte jämkas.",
    )
    claim = await _claim_for_doc(
        session,
        persisted=persisted,
        customer_id=1,
        predicate="legal.adjustment_granted",
        value={"granted": False},
    )
    key = "rev-question"
    await answer_research_need(
        session,
        research_need_id="need-a",
        question_key=key,
        claim_ids=[claim.id],
        source_type="swedish_case_law",
    )
    run_a = await create_run(session, customer_id=1, module="dd", title="A")
    run_b = await create_run(session, customer_id=2, module="dd", title="B")
    set_a = await create_evidence_set(session, run_id=run_a.id)
    set_b = await create_evidence_set(session, run_id=run_b.id)
    item = research_evidence(
        research_need_id="need-a",
        source_type="swedish_case_law",
        status="found",
        excerpt="HD ansåg att villkoret inte jämkas.",
        metadata={
            "answered_by_question_key": key,
            "knowledge_claim_ids": [claim.id],
        },
    )
    await add_evidence_items(session, evidence_set_id=set_a.id, items=[item])
    await add_evidence_items(
        session,
        evidence_set_id=set_b.id,
        items=[
            research_evidence(
                research_need_id="need-b",
                source_type="swedish_case_law",
                status="found",
                excerpt="Customer B frozen answer.",
                metadata={
                    "answered_by_question_key": "other-question",
                    "knowledge_claim_ids": ["claim-b-only"],
                },
            )
        ],
    )
    await freeze_evidence_set(session, set_a.id)
    await freeze_evidence_set(session, set_b.id)
    event = (
        await session.execute(
            select(KnowledgeGraphEventRecord).where(
                KnowledgeGraphEventRecord.node_id == claim.id
            )
        )
    ).scalar_one()
    impact = await graph_impact_from_event(session, event)
    affected = await affected_frozen_evidence_sets(
        session, customer_id=1, impact=impact
    )
    assert [row.id for row in affected] == [set_a.id]
    other = await affected_frozen_evidence_sets(
        session, customer_id=2, impact=impact
    )
    assert other == []
    assert list((await session.execute(select(EvidenceSetRevalidation))).scalars().all()) == []


async def test_embedding_retrieval_excludes_other_tenant_text_units(
    session: AsyncSession,
):
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [
            EmbeddedKnowledgeChunk(
                chunk=KnowledgeChunk(
                    document_id="doc-a",
                    chunk_id="tu-a",
                    text="Customer A secret rebate is twelve percent.",
                    customer_id=1,
                    case_id=None,
                    module="dd",
                    title="Contract A",
                    metadata={"text_unit_id": "tu-a"},
                ),
                embedding=fake_embed_text("Customer A secret rebate is twelve percent."),
            ),
            EmbeddedKnowledgeChunk(
                chunk=KnowledgeChunk(
                    document_id="doc-b",
                    chunk_id="tu-b",
                    text="Customer B secret rebate is twelve percent.",
                    customer_id=2,
                    case_id=None,
                    module="dd",
                    title="Contract B",
                    metadata={"text_unit_id": "tu-b"},
                ),
                embedding=fake_embed_text("Customer B secret rebate is twelve percent."),
            ),
            EmbeddedKnowledgeChunk(
                chunk=KnowledgeChunk(
                    document_id="hd",
                    chunk_id="tu-shared",
                    text="HD held that the clause was not adjusted.",
                    customer_id=None,
                    scope_type=SCOPE_SHARED,
                    case_id=None,
                    module="dd",
                    title="NJA",
                    metadata={"text_unit_id": "tu-shared"},
                ),
                embedding=fake_embed_text("HD held that the clause was not adjusted."),
            ),
        ]
    )
    hits_a = await store.search(
        EmbeddedKnowledgeQuery(
            query=KnowledgeQuery(
                query="secret rebate twelve percent",
                scope=KnowledgeScope(customer_id=1, module="dd"),
                limit=10,
            ),
            embedding=fake_embed_text("secret rebate twelve percent"),
        )
    )
    assert {hit.metadata.get("text_unit_id") for hit in hits_a} <= {"tu-a", "tu-shared"}
    assert "tu-b" not in {hit.metadata.get("text_unit_id") for hit in hits_a}
    hits_shared = await store.search(
        EmbeddedKnowledgeQuery(
            query=KnowledgeQuery(
                query="HD held that the clause was not adjusted.",
                scope=KnowledgeScope(customer_id=2, module="dd"),
                limit=10,
            ),
            embedding=fake_embed_text("HD held that the clause was not adjusted."),
        )
    )
    assert "tu-shared" in {hit.metadata.get("text_unit_id") for hit in hits_shared}
    assert "tu-a" not in {hit.metadata.get("text_unit_id") for hit in hits_shared}


async def test_graph_events_preserve_tenant_scope(session: AsyncSession):
    persisted_a = await _persist_doc(
        session, document_id="doc-a", customer_id=1, text="A private fact."
    )
    persisted_b = await _persist_doc(
        session, document_id="doc-b", customer_id=2, text="B private fact."
    )
    claim_a = await _claim_for_doc(
        session,
        persisted=persisted_a,
        customer_id=1,
        predicate="fact.a",
        value={"v": 1},
    )
    claim_b = await _claim_for_doc(
        session,
        persisted=persisted_b,
        customer_id=2,
        predicate="fact.b",
        value={"v": 2},
    )
    events_a = await list_graph_events(session, customer_id=1, node_kind="claim")
    events_b = await list_graph_events(session, customer_id=2, node_kind="claim")
    assert {event.node_id for event in events_a} == {claim_a.id}
    assert {event.node_id for event in events_b} == {claim_b.id}
    assert all(event.scope_type == "customer" for event in events_a)
    assert all(event.customer_id == 1 for event in events_a)
    shared_doc = await _persist_doc(
        session,
        document_id="shared-doc",
        customer_id=None,
        scope_type=SCOPE_SHARED,
        source_type="lagen_nu",
        canonical_uri="https://lagen.nu/dom/nja/1",
        text="Shared holding.",
    )
    shared_claim = await _claim_for_doc(
        session,
        persisted=shared_doc,
        customer_id=None,
        scope_type=SCOPE_SHARED,
        predicate="legal.holding",
        value={"held": True},
    )
    visible = await list_graph_events(session, customer_id=1, node_kind="claim")
    assert {event.node_id for event in visible} == {claim_a.id, shared_claim.id}


async def test_ingest_keeps_embeddings_and_units_in_the_same_scope(
    session: AsyncSession,
):
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    result = await ingest_extracted_source(
        session,
        customer_id=1,
        extracted=_extracted("Customer A uploaded contract clause."),
        document=_document(
            document_id="ingested-a",
            customer_id=1,
            title="Contract",
            canonical_uri="doc://ingested-a",
        ),
        source_type="upload",
        canonical_uri="doc://ingested-a",
        content_hash="hash-ingested-a",
        embeddings=embeddings,
        vector_store=store,
    )
    assert result.status == "indexed"
    units = list((await session.execute(select(TextUnitRecord))).scalars().all())
    assert {unit.scope_type for unit in units} == {"customer"}
    assert {unit.customer_id for unit in units} == {1}
    hits = await store.search(
        EmbeddedKnowledgeQuery(
            query=KnowledgeQuery(
                query="uploaded contract clause",
                scope=KnowledgeScope(customer_id=2, module="dd"),
                limit=5,
            ),
            embedding=fake_embed_text("uploaded contract clause"),
        )
    )
    assert hits == []


async def test_answered_by_rows_are_tenant_scoped(session: AsyncSession):
    persisted = await _persist_doc(
        session, document_id="doc-a", customer_id=1, text="Private answer."
    )
    claim = await _claim_for_doc(
        session,
        persisted=persisted,
        customer_id=1,
        predicate="fact.private",
        value={"ok": True},
    )
    await answer_research_need(
        session,
        research_need_id="need-a",
        question_key="q-private",
        claim_ids=[claim.id],
        source_type="upload",
    )
    rows = list((await session.execute(select(KnowledgeClaimAnswer))).scalars().all())
    assert len(rows) == 1
    assert rows[0].scope_type == "customer"
    assert rows[0].customer_id == 1
