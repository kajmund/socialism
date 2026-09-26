"""Entities and core relationships are domain-neutral graph primitives."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund
from app.services.knowledge.claims import SUPPORTED_BY
from app.services.knowledge.entities import (
    KnowledgeEntityError,
    knowledge_entity,
    persist_knowledge_entities,
    persist_knowledge_entity,
)
from app.services.knowledge.events import list_graph_events
from app.services.knowledge.relationships import (
    ABOUT,
    CONTRADICTS,
    CORE_RELATIONS,
    PART_OF,
    SAME_AS,
    KnowledgeRelationshipError,
    knowledge_relationship,
    persist_knowledge_relationship,
    persist_knowledge_relationships,
    relationships_touching,
    require_relation,
)


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


def test_core_relations_are_closed_and_adapters_must_namespace():
    assert CORE_RELATIONS == {ABOUT, SUPPORTED_BY, CONTRADICTS, PART_OF, SAME_AS}
    assert require_relation("legal.cites") == "legal.cites"
    with pytest.raises(KnowledgeRelationshipError, match="unknown relation"):
        require_relation("cites")
    with pytest.raises(KnowledgeEntityError, match="empty after normalize"):
        knowledge_entity(customer_id=1, entity_type="topic", key="   ", name="x")


async def test_entity_insert_conflict_reuses_the_committed_row(session: AsyncSession):
    entity = knowledge_entity(
        customer_id=1,
        entity_type="legal.source",
        key="https://lagen.nu/1915:218#P36",
        name="36 § avtalslagen",
    )
    await persist_knowledge_entity(session, entity)
    await session.commit()
    original_get = session.get
    calls = 0

    async def hide_first_read(model, ident, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return await original_get(model, ident, **kwargs)

    session.get = hide_first_read
    stored = await persist_knowledge_entity(session, replace_name(entity))
    assert stored.id == entity.id
    assert stored.name == "36 §"


async def test_relationship_insert_conflict_reuses_the_committed_row(session: AsyncSession):
    edge = knowledge_relationship(
        customer_id=1,
        relation=ABOUT,
        from_kind="claim",
        from_id="claim-1",
        to_kind="entity",
        to_id="entity-1",
    )
    await persist_knowledge_relationship(session, edge)
    await session.commit()
    original_get = session.get
    hidden = False

    async def hide_first_edge_read(model, ident, **kwargs):
        nonlocal hidden
        if ident == edge.id and not hidden:
            hidden = True
            return None
        return await original_get(model, ident, **kwargs)

    session.get = hide_first_edge_read
    stored = await persist_knowledge_relationship(
        session,
        knowledge_relationship(
            customer_id=1,
            relation=ABOUT,
            from_kind="claim",
            from_id="claim-1",
            to_kind="entity",
            to_id="entity-1",
            extra={"note": "later"},
        ),
    )
    assert stored.id == edge.id
    assert stored.extra == {"note": "later"}
    events = await list_graph_events(
        session, customer_id=1, node_kind="relationship", node_id=edge.id
    )
    assert len(events) == 1


def replace_name(entity):
    return knowledge_entity(
        customer_id=entity.customer_id,
        entity_type=entity.entity_type,
        key=entity.key,
        name="36 §",
        extra=entity.extra,
    )


async def test_persist_about_supported_by_and_same_as(session: AsyncSession):
    court = knowledge_entity(
        customer_id=1,
        entity_type="court",
        key="Högsta domstolen",
        name="Högsta domstolen",
    )
    alias = knowledge_entity(
        customer_id=1,
        entity_type="court",
        key="HD",
        name="HD",
    )
    await persist_knowledge_entities(session, [court, alias])
    edges = [
        knowledge_relationship(
            customer_id=1,
            relation=ABOUT,
            from_kind="claim",
            from_id="claim-1",
            to_kind="entity",
            to_id=court.id,
        ),
        knowledge_relationship(
            customer_id=1,
            relation=SUPPORTED_BY,
            from_kind="claim",
            from_id="claim-1",
            to_kind="text_unit",
            to_id="tu-42",
        ),
        knowledge_relationship(
            customer_id=1,
            relation=SAME_AS,
            from_kind="entity",
            from_id=court.id,
            to_kind="entity",
            to_id=alias.id,
        ),
        knowledge_relationship(
            customer_id=1,
            relation=PART_OF,
            from_kind="entity",
            from_id=alias.id,
            to_kind="entity",
            to_id=court.id,
        ),
        knowledge_relationship(
            customer_id=1,
            relation=CONTRADICTS,
            from_kind="claim",
            from_id="claim-1",
            to_kind="claim",
            to_id="claim-2",
        ),
    ]
    await persist_knowledge_relationships(session, edges)
    touching = await relationships_touching(
        session, customer_id=1, kind="claim", node_id="claim-1"
    )
    assert {edge.relation for edge in touching} == {ABOUT, SUPPORTED_BY, CONTRADICTS}
    stored = await persist_knowledge_entity(session, court)
    assert stored.id == court.id
    assert stored.name == "Högsta domstolen"
