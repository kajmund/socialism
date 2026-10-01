"""Durable knowledge persist is classified, identity-stable, and idempotent."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.knowledge_observation import KnowledgeObservationRecord
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    KnowledgeClaimAnswer,
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    KnowledgeEntityRecord,
    KnowledgeGraphEventRecord,
    KnowledgeRelationshipRecord,
    Kund,
)
from app.services.knowledge.audit import audit_knowledge_graph, cleanup_knowledge_graph
from app.services.knowledge.claim_rekey import backfill_source_independent_claims
from app.services.knowledge.events import utc_now
from app.services.knowledge.claims import (
    SUPPORTED_BY,
    KnowledgeClaim,
    knowledge_claim,
    persist_knowledge_claim,
    supporting_text_unit_ids_for_claim,
)
from app.services.knowledge.persistence import delete_canonical_document
from app.services.knowledge.entities import knowledge_entity
from app.services.knowledge.identity import knowledge_claim_identity, normalize_assertion
from app.services.knowledge.persist import persist_extracted_knowledge
from app.services.knowledge.persistence_class import (
    DOMAIN_KNOWLEDGE,
    RESEARCH_OBSERVATION,
    SOURCE_QUALITY,
    classify_persistence,
)
from app.services.knowledge.relationships import ABOUT, knowledge_relationship
from app.services.lagen_nu.graph_writeback import PendingGraphWrite, persist_pending_graph_writes
from tests.text_unit_fakes import persisted_text_unit


def test_normalized_assertion_ignores_llm_prose_and_run_ids():
    left = normalize_assertion(
        {
            "value": "The court held that the clause was not adjusted.",
            "excerpt": "different excerpt",
            "question": "Was the term adjusted?",
            "attempt_id": "attempt-1",
            "rationale": "because the LLM said so",
        }
    )
    right = normalize_assertion(
        {
            "value": "the court held that the clause was not adjusted",
            "excerpt": "another wording",
            "question": "Did HD adjust the term?",
            "attempt_id": "attempt-2",
        }
    )
    assert left == right


def test_claim_identity_ignores_source_document():
    first = knowledge_claim(
        customer_id=1,
        predicate="legal.adjustment_granted",
        value={"value": False},
        supporting_text_unit_ids=("tu-hold",),
    )
    second = knowledge_claim(
        customer_id=1,
        predicate="legal.adjustment_granted",
        value={"value": False},
        supporting_text_unit_ids=("tu-b",),
    )
    assert first.id == second.id
    assert first.id == knowledge_claim_identity(
        scope_key="customer:1",
        predicate="legal.adjustment_granted",
        value={"value": False},
    )


def test_different_structured_assertions_stay_distinct():
    granted = knowledge_claim_identity(
        scope_key="customer:1",
        predicate="legal.adjustment_granted",
        value={"value": False},
    )
    denied = knowledge_claim_identity(
        scope_key="customer:1",
        predicate="legal.adjustment_granted",
        value={"value": True},
    )
    assert granted != denied


def test_source_quality_and_gap_statements_are_not_domain_knowledge():
    truncated = classify_persistence(value={"value": "referatet är trunkerat"})
    assert truncated.persistence_class == SOURCE_QUALITY
    assert truncated.kind == "truncation"
    missing = classify_persistence(value={"value": "fullständiga domskäl saknas"})
    assert missing.persistence_class == SOURCE_QUALITY
    gap = classify_persistence(value={"value": "this source does not answer the question"})
    assert gap.persistence_class == RESEARCH_OBSERVATION
    holding = classify_persistence(value={"value": False})
    assert holding.persistence_class == DOMAIN_KNOWLEDGE
    rule = classify_persistence(value={"value": "the rule does not apply to commercial parties"})
    assert rule.persistence_class == DOMAIN_KNOWLEDGE
    incomplete = classify_persistence(value={"value": "the complete source text is missing"})
    assert incomplete.persistence_class == SOURCE_QUALITY
    exception_gap = classify_persistence(value={"value": "an exception is missing from the rule"})
    assert exception_gap.persistence_class == DOMAIN_KNOWLEDGE


async def _session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = factory()
    session.add(Kund(id=1, name="acme", slug="acme", available_modules=["dd"]))
    await session.flush()
    await _document(session)
    return session


async def _document(session: AsyncSession) -> None:
    session.add(
        CanonicalDocumentRecord(
            id="doc-a",
            customer_id=1,
            source_type="upload",
            canonical_uri="doc://a",
            title="A",
            extra={},
        )
    )
    session.add(
        DocumentVersionRecord(
            id="ver-a",
            document_id="doc-a",
            customer_id=1,
            content_hash="hash",
            mime_type="text/plain",
            extra={},
        )
    )
    session.add(
        await persisted_text_unit(session,
            id="tu-hold",
            document_version_id="ver-a",
            document_id="doc-a",
            customer_id=1,
            section_id=None,
            ordinal=0,
            text="The court held that the clause was not adjusted.",
        )
    )
    session.add(
        await persisted_text_unit(session,
            id="tu-extra",
            document_version_id="ver-a",
            document_id="doc-a",
            customer_id=1,
            section_id=None,
            ordinal=1,
            text="The lease was signed in 1998.",
        )
    )
    await session.flush()


async def _second_document(session: AsyncSession) -> None:
    session.add(
        CanonicalDocumentRecord(
            id="doc-b",
            customer_id=1,
            source_type="upload",
            canonical_uri="doc://b",
            title="B",
            extra={},
        )
    )
    session.add(
        DocumentVersionRecord(
            id="ver-b",
            document_id="doc-b",
            customer_id=1,
            content_hash="hash-b",
            mime_type="text/plain",
            extra={},
        )
    )
    session.add(
        await persisted_text_unit(session,
            id="tu-b",
            document_version_id="ver-b",
            document_id="doc-b",
            customer_id=1,
            section_id=None,
            ordinal=0,
            text="The court held that the clause was not adjusted.",
        )
    )
    await session.flush()


def _domain_claim(value: object = False, *unit_ids: str) -> KnowledgeClaim:
    return knowledge_claim(
        customer_id=1,
        predicate="legal.adjustment_granted",
        value={"value": value},
        supporting_text_unit_ids=unit_ids or ("tu-hold",),
    )


async def test_wording_variants_reuse_the_same_durable_claim():
    session = await _session()
    first = knowledge_claim(
        customer_id=1,
        predicate="legal.rule_or_principle",
        value={
            "value": "The court held that the clause was not adjusted.",
            "excerpt": "first excerpt",
            "attempt_id": "run-1",
        },
        supporting_text_unit_ids=("tu-hold",),
    )
    second = knowledge_claim(
        customer_id=1,
        predicate="legal.rule_or_principle",
        value={
            "value": "the court held that the clause was not adjusted",
            "excerpt": "second excerpt",
            "attempt_id": "run-2",
        },
        supporting_text_unit_ids=("tu-extra",),
    )
    result = await persist_extracted_knowledge(session, claims=[first, second])
    assert first.id == second.id
    assert result.stats.claims_accepted == 1
    assert result.stats.claims_reused == 1
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 1
    assert set(await supporting_text_unit_ids_for_claim(session, first.id)) == {
        "tu-hold",
        "tu-extra",
    }
    await session.close()


async def test_repeated_research_does_not_grow_the_graph():
    session = await _session()
    claim = _domain_claim()
    entity = knowledge_entity(
        customer_id=1,
        entity_type="legal.source",
        key="https://lagen.nu/dom/nja/2005s142",
        name="NJA 2005 s. 142",
    )
    edge = knowledge_relationship(
        customer_id=1,
        relation=ABOUT,
        from_kind="claim",
        from_id=claim.id,
        to_kind="entity",
        to_id=entity.id,
    )
    first = await persist_extracted_knowledge(
        session, claims=[claim], entities=[entity], relationships=[edge]
    )
    second = await persist_extracted_knowledge(
        session, claims=[claim], entities=[entity], relationships=[edge]
    )
    assert first.stats.claims_accepted == 1
    assert second.stats.claims_accepted == 0
    assert second.stats.claims_reused == 1
    assert second.stats.entities_reused == 1
    assert second.stats.relationships_reused == 1
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 1
    assert await session.scalar(select(func.count()).select_from(KnowledgeEntityRecord)) == 1
    assert await session.scalar(select(func.count()).select_from(KnowledgeRelationshipRecord)) == 1
    await session.close()


async def test_paraphrased_question_reuses_durable_knowledge():
    session = await _session()
    claim = _domain_claim()
    item = PendingGraphWrite(
        claims=(claim,),
        entities=(),
        edges=(),
        research_need_id="need-1",
        question="Was the contractual term adjusted?",
        source_type="swedish_law",
        customer_id=1,
    )
    await persist_pending_graph_writes(session, [item])
    paraphrase = PendingGraphWrite(
        claims=(claim,),
        entities=(),
        edges=(),
        research_need_id="need-2",
        question="Did the court adjust the term in the contract?",
        source_type="swedish_law",
        customer_id=1,
    )
    await persist_pending_graph_writes(session, [paraphrase])
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 1
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimAnswer)) == 2
    await session.close()


async def test_source_quality_and_gaps_do_not_enter_knowledge_claims():
    session = await _session()
    quality = knowledge_claim(
        customer_id=1,
        predicate="legal.limitation",
        value={"value": "referatet är trunkerat"},
        supporting_text_unit_ids=("tu-hold",),
    )
    gap = knowledge_claim(
        customer_id=1,
        predicate="legal.limitation",
        value={"value": "this source does not answer the research question"},
        supporting_text_unit_ids=("tu-hold",),
    )
    result = await persist_extracted_knowledge(
        session,
        claims=[quality, gap],
        question_key="was-the-term-adjusted",
    )
    assert result.stats.claims_rejected_by_class == 2
    assert result.accepted_claim_ids == []
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 0
    classes = {
        row[0]
        for row in (
            await session.execute(select(KnowledgeObservationRecord.observation_class))
        ).all()
    }
    assert classes == {SOURCE_QUALITY, RESEARCH_OBSERVATION}
    await session.close()


async def test_new_provenance_attaches_without_changing_identity():
    session = await _session()
    first = _domain_claim(False, "tu-hold")
    await persist_knowledge_claim(session, first)
    again = _domain_claim(False, "tu-extra")
    stored = await persist_knowledge_claim(session, again)
    assert stored.id == first.id
    assert stored.identity_key == first.id
    assert set(await supporting_text_unit_ids_for_claim(session, first.id)) == {
        "tu-hold",
        "tu-extra",
    }
    await session.close()


async def test_cleanup_rewires_then_removes_duplicates():
    session = await _session()
    claim = _domain_claim()
    await persist_extracted_knowledge(session, claims=[claim])
    now = utc_now()
    junk = KnowledgeClaimRecord(
        id="legacy-quality",
        identity_key="legacy-quality",
        predicate="legal.limitation",
        value={"value": "fullständiga domskäl saknas"},
        created_at=now,
        customer_id=1,
    )
    session.add(junk)
    session.add(
        KnowledgeClaimTextUnit(
            claim_id="legacy-quality",
            text_unit_id="tu-hold",
            ordinal=0,
            relation=SUPPORTED_BY,
        )
    )
    await session.flush()
    dry = await cleanup_knowledge_graph(session, apply=False)
    assert dry["applied"] is False
    assert dry["source_quality_claim_count"] == 1
    assert await session.get(KnowledgeClaimRecord, "legacy-quality") is not None
    applied = await cleanup_knowledge_graph(session, apply=True)
    assert applied["applied"] is True
    assert applied["source_quality_claim_count"] == 0
    assert await session.get(KnowledgeClaimRecord, "legacy-quality") is None
    assert await session.scalar(select(func.count()).select_from(KnowledgeObservationRecord)) == 1
    report = await audit_knowledge_graph(session)
    assert report.source_quality_claim_count == 0
    assert report.domain_claim_count == 1
    await session.close()


async def test_same_assertion_from_two_documents_reuses_one_claim():
    session = await _session()
    await _second_document(session)
    first = knowledge_claim(
        customer_id=1,
        predicate="legal.adjustment_granted",
        value={"value": False},
        supporting_text_unit_ids=("tu-hold",),
    )
    second = knowledge_claim(
        customer_id=1,
        predicate="legal.adjustment_granted",
        value={"value": False},
        supporting_text_unit_ids=("tu-b",),
    )
    result = await persist_extracted_knowledge(session, claims=[first, second])
    assert first.id == second.id
    assert result.stats.claims_accepted == 1
    assert result.stats.claims_reused == 1
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 1
    assert set(await supporting_text_unit_ids_for_claim(session, first.id)) == {
        "tu-hold",
        "tu-b",
    }
    await session.close()


async def test_cleanup_merges_duplicate_claim_edges_without_unique_violation():
    session = await _session()
    now = utc_now()
    session.add(
        KnowledgeEntityRecord(
            id="entity-x",
            entity_type="org",
            entity_key="source-x",
            name="Source X",
            extra={},
            customer_id=1,
        )
    )
    for claim_id, extra in (
        ("legacy-claim-a", {"sources": ["doc-a"]}),
        ("legacy-claim-b", {"sources": ["doc-b"]}),
    ):
        session.add(
            KnowledgeClaimRecord(
                id=claim_id,
                identity_key=claim_id,
                predicate="legal.adjustment_granted",
                value={"value": False},
                created_at=now,
                customer_id=1,
            )
        )
        session.add(
            KnowledgeRelationshipRecord(
                id=f"edge-{claim_id}",
                relation=ABOUT,
                from_kind="claim",
                from_id=claim_id,
                to_kind="entity",
                to_id="entity-x",
                temporal_key="",
                extra=extra,
                created_at=now,
                customer_id=1,
            )
        )
    session.add(
        KnowledgeGraphEventRecord(
            id="evt-loser-claim",
            event_type="CLAIM_ADDED",
            node_kind="claim",
            node_id="legacy-claim-b",
            payload={},
            created_at=now,
            customer_id=1,
        )
    )
    await session.flush()
    applied = await cleanup_knowledge_graph(session, apply=True)
    assert applied["applied"] is True
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 1
    edges = list((await session.execute(select(KnowledgeRelationshipRecord))).scalars().all())
    assert len(edges) == 1
    assert edges[0].from_id == "legacy-claim-a"
    assert edges[0].to_id == "entity-x"
    assert edges[0].extra["sources"] == ["doc-a", "doc-b"]
    event = await session.get(KnowledgeGraphEventRecord, "evt-loser-claim")
    assert event is not None
    assert event.node_id == "legacy-claim-a"
    await session.close()


async def test_cleanup_merges_duplicate_entity_edges_without_unique_violation():
    session = await _session()
    now = utc_now()
    session.add(
        KnowledgeClaimRecord(
            id="claim-keep",
            identity_key="claim-keep",
            predicate="legal.adjustment_granted",
            value={"value": True},
            created_at=now,
            customer_id=1,
        )
    )
    session.add(
        KnowledgeEntityRecord(
            id="legacy-ent-a",
            entity_type="org",
            entity_key="Court X",
            name="Court X",
            extra={"aliases": ["A"]},
            created_at=now,
            customer_id=1,
        )
    )
    session.add(
        KnowledgeEntityRecord(
            id="legacy-ent-b",
            entity_type="org",
            entity_key="court  x",
            name="Court X",
            extra={"aliases": ["B"]},
            created_at=now,
            customer_id=1,
        )
    )
    for entity_id, extra in (
        ("legacy-ent-a", {"sources": ["a"]}),
        ("legacy-ent-b", {"sources": ["b"]}),
    ):
        session.add(
            KnowledgeRelationshipRecord(
                id=f"in-{entity_id}",
                relation=ABOUT,
                from_kind="claim",
                from_id="claim-keep",
                to_kind="entity",
                to_id=entity_id,
                temporal_key="",
                extra=extra,
                created_at=now,
                customer_id=1,
            )
        )
        session.add(
            KnowledgeRelationshipRecord(
                id=f"out-{entity_id}",
                relation=ABOUT,
                from_kind="entity",
                from_id=entity_id,
                to_kind="document",
                to_id="doc-a",
                temporal_key="",
                extra={"docs": [entity_id]},
                created_at=now,
                customer_id=1,
            )
        )
    await session.flush()
    applied = await cleanup_knowledge_graph(session, apply=True)
    assert applied["applied"] is True
    assert await session.scalar(select(func.count()).select_from(KnowledgeEntityRecord)) == 1
    winner = await session.get(KnowledgeEntityRecord, "legacy-ent-a")
    assert winner is not None
    assert winner.extra["aliases"] == ["A", "B"]
    edges = list((await session.execute(select(KnowledgeRelationshipRecord))).scalars().all())
    assert len(edges) == 2
    incoming = next(edge for edge in edges if edge.from_kind == "claim")
    outgoing = next(edge for edge in edges if edge.from_kind == "entity")
    assert incoming.to_id == "legacy-ent-a"
    assert incoming.extra["sources"] == ["a", "b"]
    assert outgoing.from_id == "legacy-ent-a"
    assert outgoing.to_id == "doc-a"
    await session.close()


async def test_deleting_one_supporting_document_keeps_claim_with_other_support():
    session = await _session()
    await _second_document(session)
    first = _domain_claim(False, "tu-hold")
    second = _domain_claim(False, "tu-b")
    result = await persist_extracted_knowledge(session, claims=[first, second])
    assert first.id == second.id
    assert result.stats.claims_accepted == 1
    assert result.stats.claims_reused == 1
    await delete_canonical_document(session, "doc-a")
    remaining = await session.get(KnowledgeClaimRecord, first.id)
    assert remaining is not None
    assert remaining.superseded_at is None
    assert set(await supporting_text_unit_ids_for_claim(session, first.id)) == {"tu-b"}
    assert await session.get(CanonicalDocumentRecord, "doc-a") is None
    assert await session.get(CanonicalDocumentRecord, "doc-b") is not None
    await session.close()


def _legacy_claim(
    session: AsyncSession,
    *,
    claim_id: str,
    unit_id: str,
) -> None:
    session.add(
        KnowledgeClaimRecord(
            id=claim_id,
            identity_key=claim_id,
            predicate="legal.adjustment_granted",
            value={"value": False},
            created_at=utc_now(),
            customer_id=1,
        )
    )
    session.add(
        KnowledgeClaimTextUnit(
            claim_id=claim_id,
            text_unit_id=unit_id,
            ordinal=0,
            relation=SUPPORTED_BY,
        )
    )


async def test_legacy_singleton_is_rekeyed_to_source_independent_identity():
    session = await _session()
    expected = knowledge_claim_identity(
        scope_key="customer:1",
        predicate="legal.adjustment_granted",
        value={"value": False},
    )
    _legacy_claim(session, claim_id="legacy-old-hash", unit_id="tu-hold")
    await session.flush()
    await backfill_source_independent_claims(session)
    row = await session.get(KnowledgeClaimRecord, "legacy-old-hash")
    assert row is not None
    assert row.identity_key == expected
    assert row.identity_key != "legacy-old-hash"
    await session.close()


async def test_backfill_then_research_does_not_mint_a_second_claim():
    session = await _session()
    _legacy_claim(session, claim_id="legacy-old-hash", unit_id="tu-hold")
    await session.flush()
    await backfill_source_independent_claims(session)
    claim = _domain_claim()
    result = await persist_extracted_knowledge(session, claims=[claim])
    assert result.stats.claims_accepted == 0
    assert result.stats.claims_reused == 1
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 1
    stored = await session.get(KnowledgeClaimRecord, "legacy-old-hash")
    assert stored is not None
    assert stored.identity_key == claim.id
    await session.close()


async def test_backfill_merges_legacy_claims_from_two_documents():
    session = await _session()
    await _second_document(session)
    expected = knowledge_claim_identity(
        scope_key="customer:1",
        predicate="legal.adjustment_granted",
        value={"value": False},
    )
    _legacy_claim(session, claim_id="legacy-a", unit_id="tu-hold")
    _legacy_claim(session, claim_id="legacy-b", unit_id="tu-b")
    await session.flush()
    await backfill_source_independent_claims(session)
    assert await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord)) == 1
    winner = (await session.execute(select(KnowledgeClaimRecord))).scalar_one()
    assert winner.identity_key == expected
    assert set(await supporting_text_unit_ids_for_claim(session, winner.id)) == {
        "tu-hold",
        "tu-b",
    }
    await session.close()
