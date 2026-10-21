"""Claims and edges carry valid/system time and emit graph events."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    Kund,
)
from app.services.knowledge.claims import (
    KnowledgeClaim,
    KnowledgeClaimError,
    knowledge_claim_id,
    persist_knowledge_claim,
    supersede_knowledge_claim,
)
from app.services.knowledge.events import (
    CLAIM_ADDED,
    CLAIM_SUPERSEDED,
    EDGE_ADDED,
    list_graph_events,
)
from app.services.knowledge.entities import knowledge_entity, persist_knowledge_entity
from app.services.knowledge.relationships import (
    ABOUT,
    knowledge_relationship,
    persist_knowledge_relationship,
)
from tests.text_unit_fakes import persisted_text_unit


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
        db.add(Kund(id=1, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db
    await engine.dispose()


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
    await persisted_text_unit(session,
            id="tu-hold",
            document_version_id="ver-a",
            document_id="doc-a",
            customer_id=1,
            section_id=None,
            ordinal=0,
            text="The court held X.",
        )
    await session.flush()


def _claim(*, value: object, predicate: str = "outcome.granted") -> KnowledgeClaim:
    payload = {"value": value}
    return KnowledgeClaim(
        id=knowledge_claim_id(
            scope_key="customer:1",
            predicate=predicate,
            value=payload,
        ),
        customer_id=1,
        predicate=predicate,
        value=payload,
        supporting_text_unit_ids=("tu-hold",),
    )


async def test_persist_claim_and_edge_emit_added_events(session: AsyncSession):
    await _document(session)
    first = _claim(value=False)
    stored = await persist_knowledge_claim(session, first)
    assert stored.id == first.id
    assert stored.id == first.id
    target = await persist_knowledge_entity(
        session,
        knowledge_entity(customer_id=1, entity_type="concept", key="entity-1", name="Entity"),
    )
    edge = knowledge_relationship(
        customer_id=1,
        relation=ABOUT,
        from_kind="claim",
        from_id=first.id,
        to_kind="entity",
        to_id=target.id,
    )
    rel = await persist_knowledge_relationship(session, edge)
    assert rel.id
    events = await list_graph_events(session, customer_id=1)
    assert [item.event_type for item in events] == [CLAIM_ADDED, EDGE_ADDED]
    await persist_knowledge_claim(session, first)
    assert [item.event_type for item in await list_graph_events(session, customer_id=1)] == [
        CLAIM_ADDED,
        EDGE_ADDED,
    ]


async def test_supersede_claim_closes_time_and_rejects_rewrite(session: AsyncSession):
    await _document(session)
    old = _claim(value=False)
    new = _claim(value=True)
    await persist_knowledge_claim(session, old)
    closed = await supersede_knowledge_claim(session, old.id, successor=new)
    assert closed.id == old.id
    types = [item.event_type for item in await list_graph_events(session, customer_id=1)]
    assert types == [CLAIM_ADDED, CLAIM_SUPERSEDED, CLAIM_ADDED]
    superseded = next(
        item
        for item in await list_graph_events(session, customer_id=1, node_id=old.id)
        if item.event_type == CLAIM_SUPERSEDED
    )
    assert superseded.related_id == new.id
    with pytest.raises(KnowledgeClaimError, match="already superseded"):
        await supersede_knowledge_claim(session, old.id)
    with pytest.raises(KnowledgeClaimError, match="superseded"):
        await persist_knowledge_claim(session, old)
