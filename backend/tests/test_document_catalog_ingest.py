"""Step A: persisted documents become searchable in the tenant OverGraph."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphIngestWork
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund
from app.services.document_qa.catalog_outbox import enqueue_document_catalog
from app.services.document_qa.kinds import DOCUMENT_CATALOG_WRITE
from app.services.document_find.category_index import documents_for_type
from app.services.document_find.taxonomy import LEASE
from app.services.document_qa.labels import CANONICAL_DOCUMENT, HAS_VERSION, QUESTION, TEXT_UNIT
from app.services.document_qa.tenants import TenantCatalogs, set_tenant_catalogs
from app.services.graph_v2.outbox import process_graph_work
from app.services.knowledge.units import hash_text
from app.services.overgraph.labels import CONTAINS, DOCUMENT_VERSION
from tests.text_unit_fakes import persisted_text_unit

DIM = 8
OUTBOX = Path(__file__).resolve().parents[1] / "app/services/document_qa/catalog_outbox.py"


class FakeEmbedder:
    model = "test"
    dimension = DIM
    provider_id = "test"

    async def embed(self, texts):
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]


def _scope(customer_id=1):
    return {
        "scope_type": "customer",
        "scope_key": f"customer:{customer_id}",
        "customer_id": customer_id,
    }


async def _seed(session, *, customer_id=1):
    if await session.get(Kund, customer_id) is None:
        session.add(Kund(
            id=customer_id, name=f"C{customer_id}", slug=f"c{customer_id}",
            available_modules=[],
        ))
        await session.flush()
    session.add(CanonicalDocumentRecord(
        id="doc-1", **_scope(customer_id), source_type="upload",
        canonical_uri="doc://doc-1", title="Hyresavtal lokal", extra={},
    ))
    session.add(DocumentVersionRecord(
        id="ver-1", **_scope(customer_id), document_id="doc-1",
        content_hash=hash_text("body"), mime_type="text/plain", extra={},
    ))
    await persisted_text_unit(
        session,
        id="unit-1",
        customer_id=customer_id,
        document_id="doc-1",
        document_version_id="ver-1",
        ordinal=0,
        locator="p1",
        text="Paragraf 12 reglerar uppsägning.",
    )


@pytest.fixture
def catalogs(tmp_path):
    registry = TenantCatalogs(tmp_path, dimension=DIM)
    set_tenant_catalogs(registry)
    try:
        yield registry
    finally:
        set_tenant_catalogs(None)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/catalog.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


def test_producer_never_opens_overgraph():
    source = OUTBOX.read_text()
    assert "TenantCatalogs" not in source
    assert "open_catalog" not in source
    assert "ingest_document_units" not in source


@pytest.mark.asyncio
async def test_enqueue_does_not_create_tenant_files(factory, tmp_path):
    async with factory() as session:
        await _seed(session)
        work_id = await enqueue_document_catalog(
            session, customer_id=1, document_id="doc-1", document_version_id="ver-1",
        )
        await session.commit()
    async with factory() as session:
        row = await session.get(GraphIngestWork, work_id)
        assert row.status == "pending"
        assert row.payload["kind"] == DOCUMENT_CATALOG_WRITE
        assert row.payload["document_id"] == "doc-1"
        assert "customer_id" not in row.payload
    tenants = tmp_path / "tenants"
    assert not tenants.exists() or list(tenants.glob("*")) == []


@pytest.mark.asyncio
async def test_units_are_searchable_and_retry_is_idempotent(factory, catalogs):
    async with factory() as session:
        await _seed(session)
        first = await enqueue_document_catalog(
            session, customer_id=1, document_id="doc-1", document_version_id="ver-1",
        )
        second = await enqueue_document_catalog(
            session, customer_id=1, document_id="doc-1", document_version_id="ver-1",
        )
        assert first == second
        await session.commit()
    result = await process_graph_work(factory, embedder=FakeEmbedder())
    assert result == {"completed": 1, "failed": 0}
    catalog = catalogs.open_for(1)
    document = catalog.get_by_key(CANONICAL_DOCUMENT, "doc-1")
    version = catalog.get_by_key(DOCUMENT_VERSION, "ver-1")
    unit = catalog.get_by_key(TEXT_UNIT, "unit-1")
    assert document is not None and version is not None and unit is not None
    assert document.props.get("effective_type") == LEASE
    assert documents_for_type(catalog, LEASE) == ["doc-1"]
    assert unit.props["text"] == "Paragraf 12 reglerar uppsägning."
    assert version.engine_id in catalog.neighbors(
        document.engine_id, edge_label_filter=[HAS_VERSION],
    )
    assert unit.engine_id in catalog.neighbors(
        version.engine_id, edge_label_filter=[CONTAINS],
    )
    hits = catalog.vector_search("dense", {
        "k": 5,
        "dense_query": [1.0] + [0.0] * (DIM - 1),
        "label_filter": {"labels": [TEXT_UNIT], "mode": "all"},
    })
    assert hits and hits[0][0] == unit.engine_id
    assert catalog.vector_search("dense", {
        "k": 5,
        "dense_query": [1.0] + [0.0] * (DIM - 1),
        "label_filter": {"labels": [QUESTION], "mode": "all"},
    }) == []
    async with factory() as session:
        row = await session.get(GraphIngestWork, first)
        row.status = "pending"
        row.claimed_at = None
        row.processed_at = None
        await session.commit()
    await process_graph_work(factory, embedder=FakeEmbedder())
    assert catalog.get_by_key(TEXT_UNIT, "unit-1").key == "unit-1"
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(GraphIngestWork)) == 1


@pytest.mark.asyncio
async def test_writeback_releases_the_only_connection(tmp_path, catalogs, monkeypatch):
    from app.services.document_qa import catalog_write as write_mod

    real = write_mod.write_document_units
    started = asyncio.Event()

    async def blocked(catalog, *, document_id, units):
        started.set()
        await asyncio.sleep(0.2)
        return await real(catalog, document_id=document_id, units=units)

    monkeypatch.setattr("app.services.document_qa.catalog_apply.write_document_units", blocked)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/catalog-one.db",
        pool_size=1, max_overflow=0, pool_timeout=0.3,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await _seed(session)
        await enqueue_document_catalog(
            session, customer_id=1, document_id="doc-1", document_version_id="ver-1",
        )
        await session.commit()
    task = asyncio.create_task(process_graph_work(factory, embedder=FakeEmbedder()))
    await asyncio.wait_for(started.wait(), timeout=2)
    async with factory() as session:
        assert await session.scalar(text("SELECT 1")) == 1
    assert await task == {"completed": 1, "failed": 0}
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_mode_catalog_write_uses_the_tenant_owner(
    factory, tenant_owners, monkeypatch,
):
    from app.config import settings
    from app.services.document_qa.owner_find import run_find
    from app.services.document_find.request import FindRequest

    client = await tenant_owners(1, dimension=DIM)
    monkeypatch.setattr(settings, "overgraph_tenant_owner_sockets", "1=/tmp/tenant.sock")
    async with factory() as session:
        await _seed(session)
        work_id = await enqueue_document_catalog(
            session, customer_id=1, document_id="doc-1", document_version_id="ver-1",
        )
        await session.commit()
    result = await process_graph_work(
        factory, limit=1, kinds=[DOCUMENT_CATALOG_WRITE], embedder=FakeEmbedder(),
    )
    assert result == {"completed": 1, "failed": 0}
    async with factory() as session:
        row = await session.get(GraphIngestWork, work_id)
        assert row.status == "completed"
    found = await run_find(
        client, FindRequest(customer_id=1, query="visa alla hyresavtal", mode="replace"),
    )
    assert found.document_ids == ("doc-1",)
    read = await client.read([
        {"label": CANONICAL_DOCUMENT, "key": "doc-1"},
        {"label": TEXT_UNIT, "key": "unit-1"},
    ], include_vectors=True)
    assert read["values"][f"{CANONICAL_DOCUMENT}:doc-1"]["effective_type"] == LEASE
    assert read["ids"][f"{TEXT_UNIT}:unit-1"] is not None


@pytest.mark.asyncio
async def test_document_work_filter_skips_legal_projection(factory):
    from app.services.graph_v2.outbox import claim_graph_work

    async with factory() as session:
        await _seed(session)
        session.add(GraphIngestWork(
            id="legal-work", customer_id=1, scope_key="customer:1",
            payload={"module": "dd", "claims": [], "entities": []},
            status="pending", attempts=0,
        ))
        await session.commit()
    assert await claim_graph_work(factory, kinds=[DOCUMENT_CATALOG_WRITE]) is None
    async with factory() as session:
        assert (await session.get(GraphIngestWork, "legal-work")).status == "pending"
