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
    KnowledgeEntityRecord,
    KnowledgeRelationshipRecord,
    Kund,
    TextUnitRecord,
)
from app.services.knowledge.audit import audit_knowledge_graph, cleanup_knowledge_graph
from app.services.knowledge.events import utc_now
from app.services.knowledge.claims import (
    KnowledgeClaim,
    knowledge_claim,
    persist_knowledge_claim,
    supporting_text_unit_ids_for_claim,
)
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


def test_different_structured_assertions_stay_distinct():
    granted = knowledge_claim_identity(
        scope_key="customer:1",
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="legal.adjustment_granted",
        value={"value": False},
    )
    denied = knowledge_claim_identity(
        scope_key="customer:1",
        document_id="doc-a",
        document_version_id="ver-a",
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
        TextUnitRecord(
            id="tu-hold",
            document_version_id="ver-a",
            document_id="doc-a",
            customer_id=1,
            section_id=None,
            ordinal=0,
            text="The court held that the clause was not adjusted.",
            content_hash="tu-hold",
        )
    )
    session.add(
        TextUnitRecord(
            id="tu-extra",
            document_version_id="ver-a",
            document_id="doc-a",
            customer_id=1,
            section_id=None,
            ordinal=1,
            text="The lease was signed in 1998.",
            content_hash="tu-extra",
        )
    )
    await session.flush()


def _domain_claim(value: object = False, *unit_ids: str) -> KnowledgeClaim:
    return knowledge_claim(
        customer_id=1,
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="legal.adjustment_granted",
        value={"value": value},
        supporting_text_unit_ids=unit_ids or ("tu-hold",),
    )


async def test_wording_variants_reuse_the_same_durable_claim():
    session = await _session()
    first = knowledge_claim(
        customer_id=1,
        document_id="doc-a",
        document_version_id="ver-a",
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
        document_id="doc-a",
        document_version_id="ver-a",
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
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="legal.limitation",
        value={"value": "referatet är trunkerat"},
        supporting_text_unit_ids=("tu-hold",),
    )
    gap = knowledge_claim(
        customer_id=1,
        document_id="doc-a",
        document_version_id="ver-a",
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
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="legal.limitation",
        value={"value": "fullständiga domskäl saknas"},
        created_at=now,
        customer_id=1,
    )
    session.add(junk)
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
