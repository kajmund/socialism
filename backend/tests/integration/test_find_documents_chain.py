"""Measure find_documents OverGraph chain used by experts (show_document_set is client)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, Kund, StoredObject, UserAccount
from app.schemas.workspace import WorkspaceDocumentSet, WorkspaceState
from app.services.document_find.fixture import add_document, vector
from app.services.document_find.id_map import source_ids_for_documents
from app.services.document_find import FindRequest, run_find
from app.services.document_qa.tenants import TenantCatalogs, set_tenant_catalogs
from app.services.workspace import tool_handlers as handlers
from app.services.workspace.tool_handlers import ToolContext, find_documents
from app.services.workspaces import ensure_company_workspace

pytestmark = pytest.mark.integration

BASELINE_DIR = Path(__file__).resolve().parent / "baselines"
DIM = 8
LEASE_FILLER = vector(0.1, 0.9)


@pytest.fixture
def catalogs(tmp_path):
    registry = TenantCatalogs(tmp_path / "tenants", dimension=DIM)
    set_tenant_catalogs(registry)
    try:
        yield registry
    finally:
        set_tenant_catalogs(None)
        registry.close()


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/chain.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _seed_docs(catalog, session, *, count: int = 5) -> str:
    session.add(Kund(id=1, name="C1", slug="c1", available_modules=[]))
    session.add(UserAccount(id="user-1", email="user-1@test.local", role="user", kund_id=1))
    await session.flush()
    common = await ensure_company_workspace(session, customer_id=1)
    for index in range(count):
        doc_id = f"lease-{index}"
        await add_document(
            catalog,
            document_id=doc_id,
            title=f"Hyresavtal {index}",
            opening="Hyresavtal för lokal.",
            passages=[("Hyresavtal text.", LEASE_FILLER)],
        )
        session.add(StoredObject(
            id=f"src-lease-{index}",
            customer_id=1,
            workspace_id=common.id,
            module="dd",
            kind="document",
            bucket="c1",
            object_key=f"src-lease-{index}",
            filename=f"lease-{index}.pdf",
            content_type="application/pdf",
            size_bytes=1,
        ))
        session.add(CanonicalDocumentRecord(
            id=doc_id,
            scope_type="customer",
            scope_key="customer:1",
            customer_id=1,
            source_object_id=f"src-lease-{index}",
            source_type="upload",
            canonical_uri=f"doc://{doc_id}",
            title=f"Hyresavtal {index}",
            extra={},
        ))
    await session.commit()
    return common.id


@pytest.mark.asyncio
async def test_find_documents_category_chain_latency(factory, catalogs, monkeypatch):
    catalog = catalogs.open_for(1)
    async with factory() as session:
        common_id = await _seed_docs(catalog, session, count=5)

        async def fake_require(session, workspace_id, user):
            return SimpleNamespace(id=workspace_id, customer_id=1, owner_user_id="user-1")

        monkeypatch.setattr(handlers, "require_workspace", fake_require)
        operation = SimpleNamespace(external_started=False)
        workspace = SimpleNamespace(id="ws-1", workspace_id=common_id, customer_id=1, owner_user_id="user-1")
        user = SimpleNamespace(id="user-1")
        started = time.perf_counter()
        result = await find_documents(
            ToolContext(
                session=session,
                workspace=workspace,
                user=user,
                operation=operation,
                state=WorkspaceState(),
                language="sv",
            ),
            {"query": "Visa alla hyresavtal.", "mode": "replace"},
        )
        wall_ms = (time.perf_counter() - started) * 1000

    assert result["strategy"] == "category"
    assert result["completeness"] == "complete"
    assert result["counters"]["embedding_calls"] == 0
    assert result["counters"]["jev_calls"] == 0
    assert result["counters"]["vector_searches"] == 0
    assert result["document_count"] == 5
    assert len(result["source_ids"]) == 5
    assert result["presentation_truncated"] is False
    payload = {
        "chain": "find_documents_category",
        "document_count": result["document_count"],
        "strategy": result["strategy"],
        "db_ms": result["db_ms"],
        "total_ms": result["total_ms"],
        "wall_ms": wall_ms,
        "counters": result["counters"],
    }
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    (BASELINE_DIR / "document-find-expert-chain-v1.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8",
    )
    # The category chain now also materializes the readable workspace scope.
    # Keep a wall budget that stays meaningful (an accidental embedding call
    # takes orders of magnitude longer) but tolerates shared-CI noise, where
    # this same chain has been observed at ~350 ms while the local wall time
    # is single-digit milliseconds.
    assert wall_ms < 1000.0


@pytest.mark.asyncio
async def test_find_documents_within_active_set(factory, catalogs, monkeypatch):
    catalog = catalogs.open_for(1)
    async with factory() as session:
        session.add(Kund(id=1, name="C1", slug="c1", available_modules=[]))
        session.add(UserAccount(id="user-1", email="user-1@test.local", role="user", kund_id=1))
        await session.flush()
        common = await ensure_company_workspace(session, customer_id=1)
        for index in range(3):
            doc_id = f"lease-{index}"
            await add_document(
                catalog,
                document_id=doc_id,
                title=f"Hyresavtal {index}",
                opening="Hyresavtal.",
                passages=[
                    ("Hyresavtal.", LEASE_FILLER),
                    (
                        "Avtalet förlängs automatiskt." if index < 2 else "Ingen förlängning.",
                        vector(0.9, 0.1) if index < 2 else LEASE_FILLER,
                    ),
                ],
            )
            session.add(StoredObject(
                id=f"src-lease-{index}",
                customer_id=1,
                workspace_id=common.id,
                module="dd",
                kind="document",
                bucket="c1",
                object_key=f"src-lease-{index}",
                filename=f"lease-{index}.pdf",
                content_type="application/pdf",
                size_bytes=1,
            ))
            session.add(CanonicalDocumentRecord(
                id=doc_id,
                scope_type="customer",
                scope_key="customer:1",
                customer_id=1,
                source_object_id=f"src-lease-{index}",
                source_type="upload",
                canonical_uri=f"doc://{doc_id}",
                title=f"Hyresavtal {index}",
                extra={},
            ))
        await session.commit()

        state = WorkspaceState(
            document_sets=[
                WorkspaceDocumentSet(
                    id="set-1",
                    title="Hyresavtal",
                    source_ids=["src-lease-0", "src-lease-1", "src-lease-2"],
                )
            ],
            active_document_set_id="set-1",
            view="document_set",
        )

        async def fake_require(session, workspace_id, user):
            return SimpleNamespace(id=workspace_id, customer_id=1, owner_user_id="user-1")

        async def fake_embed(query: str):
            return vector(0.9, 0.1)

        monkeypatch.setattr(handlers, "require_workspace", fake_require)
        monkeypatch.setattr(handlers, "_find_query_embedding", fake_embed)
        result = await find_documents(
            ToolContext(
                session=session,
                workspace=SimpleNamespace(id="ws-1", workspace_id=common.id, customer_id=1, owner_user_id="user-1"),
                user=SimpleNamespace(id="user-1"),
                operation=SimpleNamespace(external_started=False),
                state=state,
                language="sv",
            ),
            {"query": "automatisk förlängning", "mode": "within"},
        )
    assert "within_set" in result["notes"]
    assert set(result["source_ids"]) <= {"src-lease-0", "src-lease-1", "src-lease-2"}
    assert {"src-lease-0", "src-lease-1"} & set(result["source_ids"])


@pytest.mark.asyncio
async def test_id_map_preserves_order(factory, catalogs):
    catalog = catalogs.open_for(1)
    async with factory() as session:
        await _seed_docs(catalog, session, count=3)
        result = run_find(
            catalog,
            FindRequest(
                customer_id=1,
                query="Visa alla hyresavtal",
                mode="replace",
                current=(),
                dense_query=None,
            ),
        )
        source_ids = await source_ids_for_documents(session, result.document_ids)
    assert len(source_ids) == len(result.document_ids)
    assert source_ids == [f"src-{doc_id}" for doc_id in result.document_ids]
