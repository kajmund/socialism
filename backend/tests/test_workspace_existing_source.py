"""A native document question reuses its existing, scoped canonical source."""

import asyncio
import json

import pytest
from sqlalchemy import delete, func, select, text

from app.database.models import DocumentVersionRecord, Job, StoredObject
from app.database.workspace_models import WorkspaceSource
from app.database.workspaces import WorkspaceMembership
from app.services import object_storage
from app.services.document_knowledge import DOCUMENT_INGEST_JOB_KIND
from app.services.knowledge.models import KnowledgeHit
from app.services.workspace import search
from tests.conftest import USER_USER_ID
from tests.test_voice_workspaces import _seed_canonical_source
from tests.test_workspace_conversations import (
    bootstrap,
    provider as provider,
    single_connection_provider as single_connection_provider,
)
from tests.test_workspace_parent_documents import _parent_canvas, _user_event


CANONICAL_TEXT = "Företagets policy kräver två godkännanden före avtalssignering."


async def _seed_policy(factory) -> dict:
    async with factory() as session:
        source = await session.get(StoredObject, "company-policy")
        source.extracted_text = CANONICAL_TEXT
        source.size_bytes = len(CANONICAL_TEXT.encode())
        source.object_key = f"expertgranskning/workspaces/{source.workspace_id}/company-policy.txt"
        await session.commit()
        return await _seed_canonical_source(session, source)


async def _native_tool(conversation, connection, name: str, arguments: dict, *, turn: int = 1):
    client, _factory, canvas, _expert, _requests = conversation
    return await client.post(f"/workspace-chat/{canvas}/sessions/{connection['session_id']}/tools/{name}",
        json={"conversation_id": connection["conversation_id"], "agent_turn": turn,
              "turn_event_key": "u1", "arguments_json": json.dumps(arguments)})


async def _successful_tool(conversation, connection, name: str, arguments: dict, *, turn: int = 1) -> dict:
    response = await _native_tool(conversation, connection, name, arguments, turn=turn)
    assert response.status_code == 200, response.text
    return response.json()


async def _counts(factory, canvas: str) -> tuple[int, int, int, int]:
    async with factory() as session:
        return (
            await session.scalar(select(func.count()).select_from(StoredObject)),
            await session.scalar(select(func.count()).select_from(Job).where(Job.kind == DOCUMENT_INGEST_JOB_KIND)),
            await session.scalar(select(func.count()).select_from(WorkspaceSource).where(WorkspaceSource.workspace_id == canvas)),
            await session.scalar(select(func.count()).select_from(DocumentVersionRecord)),
        )


async def _probe_free_connection(factory, engine) -> None:
    assert engine.pool.checkedout() == 0
    async with factory() as session:
        assert await asyncio.wait_for(session.scalar(text("SELECT 1")), 1) == 1


def _search_boundaries(factory, engine, indexed: dict, monkeypatch) -> list:
    captured = []

    class Embeddings:
        dimension = 2

        async def embed(self, values):
            await _probe_free_connection(factory, engine)
            assert values == ["Vad kräver företagets policy före signering?"]
            captured.append("embedding")
            return [[0.2, 0.3]]

    class Vectors:
        async def search(self, query):
            await _probe_free_connection(factory, engine)
            captured.append(query.query.scope)
            return [KnowledgeHit(document_id="indexed-one", provider="supabase", title="Untrusted title",
                excerpt="Invented vector excerpt that is not in the source", locator="line:1",
                score=0.9, metadata=indexed)]

    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", lambda: Embeddings())
    monkeypatch.setattr(search, "require_knowledge_vector_store", lambda: Vectors())
    return captured


async def _read_existing_policy(conversation, connection, source_id: str) -> dict:
    first = await _successful_tool(conversation, connection, "read_source", {"source_id": source_id}, turn=3)
    second = await _successful_tool(conversation, connection, "read_source", {"source_id": source_id}, turn=4)
    assert first["reference_id"] == second["reference_id"]
    assert first["number"] == second["number"] and not first["stale"]
    assert first["source_id"] == source_id and first["text"] == CANONICAL_TEXT
    assert first["excerpt"] == CANONICAL_TEXT and first["ingest_status"] == "ready"
    return first


async def _search_existing_policy(conversation, connection, indexed: dict) -> dict:
    found = await _successful_tool(conversation, connection, "search_knowledge",
        {"query": "Vad kräver företagets policy före signering?"}, turn=5)
    assert found["gaps"] == [] and len(found["items"]) == 1
    reference = found["items"][0]
    assert reference["source_id"] == "company-policy" and not reference["stale"]
    assert reference["excerpt"] == CANONICAL_TEXT and reference["title"] == "company-policy.txt"
    assert reference["snapshot"]["text_unit_id"] == indexed["text_unit_id"]
    assert reference["snapshot"]["document_version_id"] == indexed["document_version_id"]
    reread = await _successful_tool(conversation, connection, "read_source",
        {"reference_id": reference["reference_id"]}, turn=6)
    assert reread["reference_id"] == reference["reference_id"] and reread["number"] == reference["number"]
    assert reread["excerpt"] == CANONICAL_TEXT
    return reference


async def _change_download_access(factory, active: str, change: str) -> None:
    async with factory.begin() as session:
        if change == "membership":
            await session.execute(delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == active, WorkspaceMembership.user_id == USER_USER_ID))
        else:
            source = await session.get(StoredObject, "company-policy")
            if change == "object_key":
                source.object_key = "new-original-file.txt"
            else:
                source.extracted_text = "En ny policyversion med andra villkor."


async def _download_during_storage_wait(conversation, engine, company: str, monkeypatch, *,
                                        active: str | None = None, change: str | None = None) -> None:
    client, factory, canvas, _expert, _requests = conversation
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def get_object(bucket, key):
        await _probe_free_connection(factory, engine)
        calls.append((bucket, key))
        entered.set()
        await release.wait()
        return CANONICAL_TEXT.encode(), "text/plain"

    monkeypatch.setattr(object_storage, "get_object", get_object)
    task = asyncio.create_task(client.get(f"/voice-workspaces/{canvas}/sources/company-policy/file"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await _probe_free_connection(factory, engine)
        if change is not None:
            await _change_download_access(factory, active, change)
    finally:
        release.set()
        response = await task
    if change is None:
        assert response.status_code == 200, response.text
        assert response.content == CANONICAL_TEXT.encode()
        assert response.headers["content-type"].startswith("text/plain")
    else:
        assert response.status_code == (404 if change == "membership" else 409), response.text
        assert CANONICAL_TEXT.encode() not in response.content
    assert calls == [("inventory-test", f"expertgranskning/workspaces/{company}/company-policy.txt")]


@pytest.mark.parametrize("mode", ["text", "voice"])
async def test_native_question_reuses_existing_ready_company_source(single_connection_provider, user_token, monkeypatch, *, mode):
    original, engine = single_connection_provider
    conversation, company, active = await _parent_canvas(original, user_token)
    indexed = await _seed_policy(conversation[1])
    before = await _counts(conversation[1], conversation[2])
    connection = await bootstrap(conversation, mode)
    event = await _user_event(conversation, connection)
    assert event.status_code == 200, event.text
    context = json.loads(event.json()["context"])
    source_id = next(row["source_object_id"] for row in context["available_documents"] if row["filename"] == "company-policy.txt")
    assert source_id == "company-policy"
    first = await _successful_tool(conversation, connection, "ingest_source", {"source_id": source_id})
    second = await _successful_tool(conversation, connection, "ingest_source", {"source_id": source_id}, turn=2)
    assert first["status"] == second["status"] == "completed"
    assert first["source_id"] == second["source_id"] == source_id and first["ingest_status"] == "ready"
    assert first["job_id"] is None and second["job_id"] is None
    await _read_existing_policy(conversation, connection, source_id)
    captured = _search_boundaries(conversation[1], engine, indexed, monkeypatch)
    reference = await _search_existing_policy(conversation, connection, indexed)
    assert captured[0] == "embedding" and len(captured) == 2
    scope = captured[1]
    assert scope.module == "expertgranskning" and scope.customer_id == 1
    assert scope.workspace_id == active and scope.readable_workspace_ids == (company, active)
    assert scope.allowed_source_object_ids == (source_id,)
    assert scope.allowed_document_version_ids == (indexed["document_version_id"],)
    assert reference["file_url"] == f"/voice-workspaces/{conversation[2]}/sources/{source_id}/file"
    await _download_during_storage_wait(conversation, engine, company, monkeypatch)
    assert await _counts(conversation[1], conversation[2]) == (before[0], before[1], before[2] + 1, before[3])


@pytest.mark.parametrize("mode", ["text", "voice"])
@pytest.mark.parametrize("change", ["membership", "object_key", "extracted_text"])
async def test_native_source_download_revalidates_after_storage_wait(single_connection_provider, user_token, monkeypatch, *, mode, change):
    original, engine = single_connection_provider
    conversation, company, active = await _parent_canvas(original, user_token)
    await _seed_policy(conversation[1])
    connection = await bootstrap(conversation, mode)
    assert (await _user_event(conversation, connection)).status_code == 200
    await _successful_tool(conversation, connection, "ingest_source", {"source_id": "company-policy"})
    await _download_during_storage_wait(conversation, engine, company, monkeypatch, active=active, change=change)


@pytest.mark.parametrize("mode", ["text", "voice"])
@pytest.mark.parametrize("source_id", ["sibling-contract", "foreign-contract"])
async def test_native_existing_source_rejects_sibling_and_foreign_customer(single_connection_provider, user_token, monkeypatch, *, mode, source_id):
    original, _engine = single_connection_provider
    conversation, _company, _active = await _parent_canvas(original, user_token)
    connection = await bootstrap(conversation, mode)
    assert (await _user_event(conversation, connection)).status_code == 200
    before = await _counts(conversation[1], conversation[2])

    async def forbidden_storage(*_args):
        raise AssertionError("Unauthorized source reached object storage")

    monkeypatch.setattr(object_storage, "get_object", forbidden_storage)
    for name in ("ingest_source", "read_source"):
        response = await _native_tool(conversation, connection, name, {"source_id": source_id})
        assert response.status_code == 404 and "source_id" not in response.json(), response.text
    client, _factory, canvas, _expert, _requests = conversation
    response = await client.get(f"/voice-workspaces/{canvas}/sources/{source_id}/file")
    assert response.status_code == 404, response.text
    assert await _counts(conversation[1], canvas) == before
