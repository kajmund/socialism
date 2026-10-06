"""A workspace request cannot retain the only connection during external work."""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceOperation
from tests.test_pdf_quote_anchors import QUOTE, _synthetic_pdf
from app.services.workspace import ingest, search
from app.services.workspace.service import add_source, create_workspace
from app.services.workspace.tools import execute_workspace_tool


@pytest.fixture
async def single_connection(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/workspace.db", pool_size=1, max_overflow=0, pool_timeout=0.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Customer", slug="workspace-test", available_modules=["dd"]))
        await session.flush()
        user = UserAccount(id="user-one", email="user@example.test", role="user", kund_id=1)
        session.add(user)
        await session.flush()
        workspace = await create_workspace(session, user, title="Avtal", module="dd")
        ids = user.id, workspace.id
        await session.commit()
    yield factory, ids
    await engine.dispose()


async def another_client(factory):
    async with factory() as other:
        assert await asyncio.wait_for(other.scalar(text("SELECT 1")), timeout=1) == 1


async def command(factory, ids, *, name, args):
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        result = await execute_workspace_tool(session, workspace_id=ids[1], user=user,
            tool_name=name, arguments=args, idempotency_key="external-one")
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_url_fetch_and_object_storage_release_connection(single_connection, monkeypatch):
    factory, ids = single_connection
    calls = []
    async def fetch(_url):
        await another_client(factory)
        calls.append("fetch")
        return b"Source", "text/plain", "source.txt", "https://example.test/source"
    async def store(_bucket, _key, _data, _mime):
        await another_client(factory)
        calls.append("store")
    monkeypatch.setattr(ingest, "fetch_source_url", fetch)
    monkeypatch.setattr(ingest, "put_object", store)
    result = await command(factory, ids, name="ingest_source", args={"url": "https://example.test/source"})
    assert result["status"] == "queued" and calls == ["fetch", "store"]


@pytest.mark.asyncio
async def test_vector_embedding_and_search_release_connection(single_connection, monkeypatch):
    factory, ids = single_connection
    async with factory() as session:
        from app.database.workspace_models import VoiceWorkspace
        workspace = await session.get(VoiceWorkspace, ids[1])
        source = StoredObject(id="source-one", workspace_id=workspace.workspace_id, customer_id=1, owner_user_id=ids[0], module="dd", kind="underlag",
            bucket="workspace-test", object_key="source.txt", filename="source.txt", content_type="text/plain",
            size_bytes=6, extraction_status="ok", extracted_text="Source", knowledge_status="ready")
        session.add(source)
        await session.flush()
        await add_source(session, workspace, source.id)
        await session.commit()
    calls = []
    class Embeddings:
        dimension = 2
        async def embed(self, _values):
            await another_client(factory)
            calls.append("embed")
            return [[0.2, 0.3]]
    class Vector:
        async def search(self, _query):
            await another_client(factory)
            calls.append("vector")
            return []
    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", lambda: Embeddings())
    monkeypatch.setattr(search, "require_knowledge_vector_store", lambda: Vector())
    result = await command(factory, ids, name="search_knowledge", args={"query": "Source"})
    assert result["items"] == [] and calls == ["embed", "vector"]


@pytest.mark.asyncio
async def test_external_failure_is_durable_and_releases_connection(single_connection, monkeypatch):
    factory, ids = single_connection
    async def fetch(_url):
        await another_client(factory)
        raise ValueError("invalid_source")
    monkeypatch.setattr(ingest, "fetch_source_url", fetch)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await command(factory, ids, name="ingest_source", args={"url": "https://example.test/source"})
    await another_client(factory)
    async with factory() as session:
        operation = await session.scalar(select(WorkspaceOperation))
        assert operation.status == "failed"
    replay = await command(factory, ids, name="ingest_source", args={"url": "https://example.test/source"})
    assert replay["status"] == "failed"


@pytest.mark.asyncio
async def test_caller_pending_writes_are_never_committed(single_connection):
    factory, ids = single_connection
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        user.first_name = "Unrelated"
        with pytest.raises(RuntimeError, match="clean transaction"):
            await execute_workspace_tool(session, workspace_id=ids[1], user=user, tool_name="get_workspace_context",
                arguments={}, idempotency_key="dirty")
        await session.rollback()
    async with factory() as session:
        assert (await session.get(UserAccount, ids[0])).first_name is None


@pytest.mark.asyncio
async def test_general_graph_embedding_release_and_tenant_scope(single_connection, monkeypatch):
    factory, ids = single_connection
    from app.database.workspace_models import VoiceWorkspace
    from app.database.models import DocumentVersionRecord
    from app.services.workspace.sources import read_reference
    from tests.test_research_graph_v2_reuse import seed_fact, Embeddings
    async with factory() as session:
        session.add(Kund(id=2, name="Other", slug="other-customer"))
        await session.flush()
        await seed_fact(session, scope="shared")
        await seed_fact(session, scope="customer:1")
        await seed_fact(session, scope="customer:2")
        workspace = await session.get(VoiceWorkspace, ids[1])
        workspace.state = {**workspace.state, "knowledge_scope": "general"}
        await session.commit()
    class CheckedEmbeddings(Embeddings):
        async def embed(self, texts):
            await another_client(factory)
            return await super().embed(texts)
    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", CheckedEmbeddings)
    result = await command(factory, ids, name="search_knowledge", args={"query": "36 § avtalslagen senare lagändringar"})
    assert {item["source_id"] for item in result["items"]} == {"version-shared"}
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        item = result["items"][0]
        assert not (await read_reference(session, workspace, item["reference_id"]))["stale"]
        from datetime import UTC, datetime
        version = await session.get(DocumentVersionRecord, item["source_id"])
        version.superseded_at = datetime.now(UTC)
        await session.commit()
        assert (await read_reference(session, workspace, item["reference_id"]))["stale"]


async def _ready_source(factory, ids, *, content_type: str, text: str) -> None:
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        source = StoredObject(id="source-one", workspace_id=workspace.workspace_id, customer_id=1,
            owner_user_id=ids[0], module="dd", kind="underlag", bucket="workspace-test",
            object_key="source.bin", filename="avtal.pdf", content_type=content_type, size_bytes=len(text),
            extraction_status="ok", extracted_text=text, knowledge_status="ready")
        session.add(source)
        await session.flush()
        await add_source(session, workspace, source.id)
        await session.commit()


@pytest.mark.asyncio
async def test_focus_passage_releases_connection_while_reading_the_pdf(single_connection, monkeypatch):
    factory, ids = single_connection
    await _ready_source(factory, ids, content_type="application/pdf", text=QUOTE)
    calls = []

    async def get_object(_bucket, _key):
        await another_client(factory)
        calls.append("pdf")
        return _synthetic_pdf(), "application/pdf"

    monkeypatch.setattr("app.services.workspace_quote_focus.get_object", get_object)
    result = await command(factory, ids, name="focus_passage", args={"source_id": "source-one", "quote": "2031-02-03"})
    assert calls == ["pdf"]
    assert result["reference_id"]
    assert result["anchor"]["page_number"] == 1
    assert result["anchor"]["rects"]
    await another_client(factory)


@pytest.mark.asyncio
async def test_focus_passage_marks_text_without_fetching_the_file(single_connection, monkeypatch):
    factory, ids = single_connection
    await _ready_source(factory, ids, content_type="text/plain", text="Ateles Consulting AB är kunden.")

    async def get_object(_bucket, _key):
        raise AssertionError("text quotes do not need the file")

    monkeypatch.setattr("app.services.workspace_quote_focus.get_object", get_object)
    result = await command(factory, ids, name="focus_passage", args={
        "source_id": "source-one", "quote": "Ateles Consulting AB"})
    assert result["anchor"]["exact_text"] == "Ateles Consulting AB"
    assert result["anchor"]["locator"] == "passage"
    assert result["anchor"]["page_number"] is None
