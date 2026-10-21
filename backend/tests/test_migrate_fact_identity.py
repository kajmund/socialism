"""Migration of merged legacy facts to the additive, source-anchored identity."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.graph_v2 import GraphFact, GraphFactSource
from app.database.models import Kund
from app.services.knowledge.migrate_fact_identity import migrate_fact_identities
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.write import upsert_entity, upsert_text_unit


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


def _unit(unit_id: str, version: str) -> None:
    upsert_text_unit(require_knowledge(), TextUnitWrite(
        unit_id=unit_id, scope=customer_scope(1), document_id=f"doc-{version}",
        document_version_id=version, text=f"Text {unit_id}",
        content_hash=unit_id, ordinal=0,
    ))


def _endpoints() -> tuple[str, str]:
    graph = require_knowledge()
    from app.services.graph_v2.types import NodeInput

    return (
        upsert_entity(graph, NodeInput(node_type="legal.source", name="A", scope=customer_scope(1))).key,
        upsert_entity(graph, NodeInput(node_type="legal.issue", name="B", scope=customer_scope(1))).key,
    )


async def _legacy_fact(session: AsyncSession, *, fact_id: str, units: list[str]) -> None:
    source_id, target_id = _endpoints()
    session.add(GraphFact(
        id=fact_id, identity_key=fact_id, scope_key="customer:1", customer_id=1,
        source_id=source_id, target_id=target_id, predicate="legal.rule",
        fact_text="Nio månaders uppsägningstid gäller.", normalized_text="nio månaders uppsägningstid gäller.",
        occurrence_key="", status="active", attributes={},
    ))
    await session.flush()
    for unit in units:
        session.add(GraphFactSource(fact_id=fact_id, source_kind="text_unit", source_ref=unit))
    await session.flush()


async def test_merged_legacy_fact_is_materialised_per_source_occurrence(session):
    _unit("tu-1", "ver-a")
    _unit("tu-2", "ver-b")
    await _legacy_fact(session, fact_id="legacy-merged", units=["tu-1", "tu-2"])

    report = await migrate_fact_identities(session)
    assert report.total == 1
    assert report.materialised == 2
    assert report.verified is True
    assert require_knowledge().count_nodes_by_labels(["Fact"]) == 2


async def test_fact_with_episode_source_keeps_its_explicit_contract(session):
    await _legacy_fact(session, fact_id="legacy-episode", units=[])
    session.add(GraphFactSource(
        fact_id="legacy-episode", source_kind="episode", source_ref="evidence-1",
    ))
    await session.flush()
    report = await migrate_fact_identities(session)
    assert report.kept_explicit_contract == 1
    assert report.verified is True


async def test_missing_text_unit_is_reported_not_fabricated(session):
    await _legacy_fact(session, fact_id="legacy-broken", units=["tu-gone"])
    report = await migrate_fact_identities(session)
    assert report.verified is False
    assert any("tu-gone" in item for item in report.unresolved)
    assert require_knowledge().count_nodes_by_labels(["Fact"]) == 0
