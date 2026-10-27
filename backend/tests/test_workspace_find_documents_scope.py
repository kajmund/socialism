"""find_documents is confined to the user's readable org workspaces.

Regression tests for the P1 review findings:
- category/within/extend searches never surface documents or sources from a
  client workspace the user cannot read;
- the blocking tenant-catalog open + search runs on a worker thread, not the
  event loop, and the database connection is released while it runs.
"""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, Kund, StoredObject, UserAccount
from app.schemas.workspace import WorkspaceDocumentSet, WorkspaceState
from app.services.document_find.fixture import add_document, vector
from app.services.document_find.types import FindResult, OpCounters
from app.services.workspace import tool_handlers as handlers
from app.services.workspace.tool_handlers import ToolContext, find_documents
from app.services.workspaces import create_client_workspace, ensure_company_workspace

DIM = 8
USER_A = "user-1"
USER_B = "user-2"


@pytest.fixture
async def catalogs(owner_tenant_catalogs):
    return await owner_tenant_catalogs(dimension=DIM)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/scope.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


def _stored_object(object_id: str, workspace_id: str) -> StoredObject:
    return StoredObject(
        id=object_id,
        customer_id=1,
        workspace_id=workspace_id,
        module="dd",
        kind="document",
        bucket="c1",
        object_key=object_id,
        filename=f"{object_id}.pdf",
        content_type="application/pdf",
        size_bytes=1,
    )


def _canonical_document(document_id: str, object_id: str) -> CanonicalDocumentRecord:
    return CanonicalDocumentRecord(
        id=document_id,
        scope_type="customer",
        scope_key="customer:1",
        customer_id=1,
        source_object_id=object_id,
        source_type="upload",
        canonical_uri=f"doc://{document_id}",
        title=document_id,
        extra={},
    )


async def _seed_scope(factory) -> dict[str, str]:
    """Kund 1 with a company workspace and two client workspaces.

    user-1 owns and can read client A; client B belongs to user-2 and is
    unreadable for user-1.
    """
    async with factory.begin() as session:
        session.add(Kund(id=1, name="C1", slug="c1", available_modules=[]))
        await session.flush()
        session.add_all([
            UserAccount(id=USER_A, email="a@test.local", role="user", kund_id=1),
            UserAccount(id=USER_B, email="b@test.local", role="user", kund_id=1),
        ])
        await session.flush()
        common = await ensure_company_workspace(session, customer_id=1)
        client_a = await create_client_workspace(session, customer_id=1, user_id=USER_A, name="A")
        client_b = await create_client_workspace(session, customer_id=1, user_id=USER_B, name="B")
    return {"common": common.id, "a": client_a.id, "b": client_b.id}


async def _seed_documents(factory, catalogs, *, readable: bool = True) -> dict[str, str]:
    """Catalog + DB rows for one company doc and one doc per client workspace.

    With readable=False only the client B document exists, so user-1 has no
    readable documents at all.
    """
    catalog = catalogs.open_for(1)
    workspace_ids = await _seed_scope(factory)
    async with factory.begin() as session:
        if readable:
            for object_id, workspace_id, document_id in (
                ("src-common", workspace_ids["common"], "doc-common"),
                ("src-a", workspace_ids["a"], "doc-a"),
            ):
                session.add(_stored_object(object_id, workspace_id))
                session.add(_canonical_document(document_id, object_id))
                await add_document(
                    catalog,
                    document_id=document_id,
                    title="Hyresavtal",
                    opening="Hyresavtal.",
                    passages=[("Hyresavtal text.", vector(0.1, 0.9))],
                )
        for object_id, workspace_id, document_id in (
            ("src-b", workspace_ids["b"], "doc-b"),
        ):
            session.add(_stored_object(object_id, workspace_id))
            session.add(_canonical_document(document_id, object_id))
            await add_document(
                catalog,
                document_id=document_id,
                title="Hyresavtal",
                opening="Hyresavtal.",
                passages=[
                    ("Hyresavtal text.", vector(0.1, 0.9)),
                    ("Avtalet förlängs automatiskt.", vector(0.9, 0.1)),
                ],
            )
    return workspace_ids


def _context(session, workspace_id: str, state: WorkspaceState) -> ToolContext:
    return ToolContext(
        session=session,
        workspace=SimpleNamespace(
            id="ws-1",
            workspace_id=workspace_id,
            customer_id=1,
            owner_user_id=USER_A,
        ),
        user=SimpleNamespace(id=USER_A),
        operation=SimpleNamespace(external_started=False),
        state=state,
        language="sv",
    )


@pytest.fixture
def patch_workspace(monkeypatch):
    async def fake_require(session, workspace_id, user):
        return SimpleNamespace(id=workspace_id, customer_id=1, owner_user_id=USER_A)

    monkeypatch.setattr(handlers, "require_workspace", fake_require)


@pytest.mark.asyncio
async def test_category_find_excludes_unreadable_client_workspace(
    factory, catalogs, patch_workspace,
):
    workspace_ids = await _seed_documents(factory, catalogs)
    async with factory() as session:
        result = await find_documents(
            _context(session, workspace_ids["a"], WorkspaceState()),
            {"query": "Visa alla hyresavtal", "mode": "replace"},
        )
    assert result["strategy"] == "category"
    assert result["document_count"] == 2
    assert set(result["document_ids"]) == {"doc-common", "doc-a"}
    assert set(result["source_ids"]) == {"src-common", "src-a"}
    assert "doc-b" not in result["document_ids"]
    assert "src-b" not in result["source_ids"]


@pytest.mark.asyncio
async def test_within_find_stays_inside_readable_part_of_active_set(
    factory, catalogs, patch_workspace, monkeypatch,
):
    workspace_ids = await _seed_documents(factory, catalogs)

    async def fake_embed(query: str):
        return vector(0.9, 0.1)

    monkeypatch.setattr(handlers, "_find_query_embedding", fake_embed)
    state = WorkspaceState(
        document_sets=[
            WorkspaceDocumentSet(
                id="set-1",
                title="Hyresavtal",
                source_ids=["src-a", "src-b"],
            )
        ],
        active_document_set_id="set-1",
        view="document_set",
    )
    async with factory() as session:
        result = await find_documents(
            _context(session, workspace_ids["a"], state),
            {"query": "automatisk förlängning", "mode": "within"},
        )
    assert "within_set" in result["notes"]
    assert set(result["document_ids"]) == {"doc-a"}
    assert result["source_ids"] == ["src-a"]
    assert "doc-b" not in result["document_ids"]
    assert "src-b" not in result["source_ids"]


@pytest.mark.asyncio
async def test_extend_find_merges_only_readable_sources(
    factory, catalogs, patch_workspace,
):
    workspace_ids = await _seed_documents(factory, catalogs)
    state = WorkspaceState(
        document_sets=[
            WorkspaceDocumentSet(
                id="set-1",
                title="Hyresavtal",
                source_ids=["src-a", "src-b"],
            )
        ],
        active_document_set_id="set-1",
        view="document_set",
    )
    async with factory() as session:
        result = await find_documents(
            _context(session, workspace_ids["a"], state),
            {"query": "Visa alla hyresavtal", "mode": "extend"},
        )
    assert "extend" in result["notes"]
    assert set(result["document_ids"]) == {"doc-a", "doc-common"}
    assert set(result["source_ids"]) == {"src-a", "src-common"}
    assert "doc-b" not in result["document_ids"]
    assert "src-b" not in result["source_ids"]


@pytest.mark.asyncio
async def test_empty_readable_scope_returns_honest_note_without_catalog(
    factory, catalogs, patch_workspace, monkeypatch,
):
    workspace_ids = await _seed_documents(factory, catalogs, readable=False)

    def unexpected(*args, **kwargs):
        raise AssertionError("tenant catalog must not be opened")

    async def unexpected_embed(query: str):
        raise AssertionError("embedding must not be called")

    monkeypatch.setattr(handlers, "run_owner_find", unexpected)
    monkeypatch.setattr(handlers, "_find_query_embedding", unexpected_embed)
    async with factory() as session:
        result = await find_documents(
            _context(session, workspace_ids["a"], WorkspaceState()),
            {"query": "Visa alla hyresavtal", "mode": "replace"},
        )
    assert result["document_ids"] == []
    assert result["source_ids"] == []
    assert result["document_count"] == 0
    assert "no_readable_documents" in result["notes"]


@pytest.mark.asyncio
async def test_find_owner_call_releases_db(
    tmp_path, monkeypatch,
):
    """One-connection pool proves the handler does not hold its connection
    while the asynchronous Owner search is pending."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'thread.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.5,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="C1", slug="c1", available_modules=[]))
        session.add(UserAccount(id=USER_A, email="a@test.local", role="user", kund_id=1))
        await session.flush()
        common = await ensure_company_workspace(session, customer_id=1)
        session.add(_stored_object("src-1", common.id))
        session.add(_canonical_document("doc-1", "src-1"))

    entered = threading.Event()
    release = threading.Event()
    runner_ids: list[int] = []

    async def fake_find(*args, **kwargs):
        runner_ids.append(threading.get_ident())
        entered.set()
        assert await asyncio.to_thread(release.wait, 5)
        return FindResult(
            document_ids=("doc-1",),
            strategy="category",
            completeness="complete",
            counters=OpCounters(),
        )

    monkeypatch.setattr(handlers, "run_owner_find", fake_find)
    monkeypatch.setattr(handlers, "tenant_owner_client", lambda _customer_id: object())

    async def fake_require(session, workspace_id, user):
        return SimpleNamespace(id=workspace_id, customer_id=1, owner_user_id=USER_A)

    monkeypatch.setattr(handlers, "require_workspace", fake_require)
    try:
        async with factory() as session:
            task = asyncio.create_task(find_documents(
                _context(session, common.id, WorkspaceState()),
                {"query": "Visa alla hyresavtal", "mode": "replace"},
            ))
            assert await asyncio.to_thread(entered.wait, 5)
            async with factory() as probe:
                assert (await probe.get(Kund, 1)).name == "C1"
            release.set()
            result = await asyncio.wait_for(task, timeout=5)
    finally:
        release.set()
        await engine.dispose()
    assert runner_ids
    assert result["document_ids"] == ["doc-1"]
    assert result["source_ids"] == ["src-1"]
