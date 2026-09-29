"""Regression tests for Codex findings after knowledge persistence merge."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    KnowledgeEntityRecord,
    KnowledgeRelationshipRecord,
    Kund,
)
from app.services.knowledge.entities import knowledge_entity, persist_knowledge_entity_result
from app.services.knowledge.observations import (
    KnowledgeObservationError,
    ObservationSeed,
    knowledge_observation,
    persist_knowledge_observation,
)
from app.services.knowledge.persistence_class import DOMAIN_KNOWLEDGE, classify_persistence
from app.services.knowledge.relationships import (
    ABOUT,
    knowledge_relationship,
    persist_knowledge_relationship_result,
)
from app.services.knowledge.scope import customer_scope


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = factory()
    session.add_all(
        [
            Kund(id=1, name="one", slug="one", available_modules=["dd"]),
            Kund(id=2, name="two", slug="two", available_modules=["dd"]),
        ]
    )
    await session.flush()
    return session


def test_ocr_marker_does_not_match_democracy():
    result = classify_persistence(value={"value": "A democratic institution protects democracy."})
    assert result.persistence_class == DOMAIN_KNOWLEDGE


@pytest.mark.asyncio
async def test_legacy_relationship_reuses_stable_tuple_despite_old_id():
    session = await _session()
    left = knowledge_entity(customer_id=1, entity_type="org", key="a", name="A")
    right = knowledge_entity(customer_id=1, entity_type="org", key="b", name="B")
    await persist_knowledge_entity_result(session, left)
    await persist_knowledge_entity_result(session, right)
    session.add(
        KnowledgeRelationshipRecord(
            id="legacy-edge-id",
            customer_id=1,
            relation=ABOUT,
            from_kind="entity",
            from_id=left.id,
            to_kind="entity",
            to_id=right.id,
            temporal_key="",
            extra={"legacy": True},
        )
    )
    await session.flush()
    edge = knowledge_relationship(
        customer_id=1,
        relation=ABOUT,
        from_kind="entity",
        from_id=left.id,
        to_kind="entity",
        to_id=right.id,
        extra={"new": True},
    )
    row, reused = await persist_knowledge_relationship_result(session, edge)
    assert reused is True
    assert row.id == "legacy-edge-id"
    assert row.extra == {"legacy": True, "new": True}
    assert await session.scalar(select(func.count()).select_from(KnowledgeRelationshipRecord)) == 1
    await session.close()


@pytest.mark.asyncio
async def test_observation_rejects_other_tenant_provenance():
    session = await _session()
    session.add(
        CanonicalDocumentRecord(
            id="doc-two",
            customer_id=2,
            source_type="upload",
            canonical_uri="doc://two",
            title="Two",
            extra={},
        )
    )
    session.add(
        DocumentVersionRecord(
            id="ver-two",
            document_id="doc-two",
            customer_id=2,
            content_hash="hash-two",
            mime_type="text/plain",
            extra={},
        )
    )
    await session.flush()
    observation = knowledge_observation(
        ObservationSeed(
            observation_class="source_quality",
            kind="truncation",
            document_id="doc-two",
            document_version_id="ver-two",
            statement_normalized="source is truncated",
        ),
        customer_scope(1),
    )
    with pytest.raises(KnowledgeObservationError):
        await persist_knowledge_observation(session, observation)
    await session.close()


@pytest.mark.asyncio
async def test_legacy_entity_reuses_normalized_stable_key():
    session = await _session()
    session.add(
        KnowledgeEntityRecord(
            id="legacy-court",
            customer_id=1,
            entity_type="org",
            entity_key="Court  X",
            name="Court X",
            extra={"aliases": ["legacy"]},
        )
    )
    await session.flush()
    entity = knowledge_entity(
        customer_id=1,
        entity_type="org",
        key="court x",
        name="Court X",
        extra={"aliases": ["canonical"]},
    )
    row, reused = await persist_knowledge_entity_result(session, entity)
    assert reused is True
    assert row.id == "legacy-court"
    assert await session.scalar(select(func.count()).select_from(KnowledgeEntityRecord)) == 1
    await session.close()
