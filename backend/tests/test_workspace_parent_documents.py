"""Native dialogs discover parent documents without retaining DB connections."""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.database.models import Kund, StoredObject, UserAccount
from app.database.workspace_models import WorkspaceSource
from app.database.workspaces import Workspace, WorkspaceMembership
from app.services.elevenlabs_agents import ElevenLabsAgentsClient, get_elevenlabs_client
from app.services.expertgranskning.memory import set_expert_memory_factory
from tests.conftest import NoopExpertMemory, USER_USER_ID
from tests.test_workspace_conversations import (
    bootstrap,
    provider as provider,
    single_connection_provider as single_connection_provider,
)


SOURCE_TEXT = "PRIVATE DOCUMENT TEXT MUST NOT APPEAR IN THE INVENTORY"


def _document(source_id: str, workspace_id: str, *, customer_id: int = 1,
              module: str = "dd", owner_id: str = USER_USER_ID) -> StoredObject:
    return StoredObject(id=source_id, customer_id=customer_id, workspace_id=workspace_id,
        owner_user_id=owner_id, module=module, kind="underlag", bucket="inventory-test",
        object_key=source_id, filename=f"{source_id}.txt", content_type="text/plain",
        size_bytes=len(SOURCE_TEXT), extraction_status="ok", extracted_text=SOURCE_TEXT,
        knowledge_status="ready")


async def _parent_canvas(original, user_token):
    client, factory, _old_canvas, expert_id, requests = original
    client.headers["Authorization"] = "Bearer " + user_token
    response = await client.get("/workspaces")
    assert response.status_code == 200, response.text
    company = next(row["id"] for row in response.json() if row["kind"] == "company")
    active = (await client.post("/workspaces", json={"name": "Active client"})).json()["id"]
    sibling = (await client.post("/workspaces", json={"name": "Sibling client"})).json()["id"]
    response = await client.post("/voice-workspaces", json={"workspace_id": active,
        "title": "Parent document dialog", "idempotency_key": str(uuid4())})
    assert response.status_code == 201, response.text
    canvas = response.json()["id"]
    async with factory.begin() as session:
        foreign = Kund(name="Foreign organization", slug="parent-inventory-foreign", available_modules=["dd"])
        session.add(foreign)
        await session.flush()
        session.add(UserAccount(id="foreign-owner", email="foreign@inventory.test", role="user", kund_id=foreign.id))
        session.add(Workspace(id="foreign-company", customer_id=foreign.id, name="Foreign company", kind="company"))
        await session.flush()
        session.add_all([
            _document("company-policy", company, module="expertgranskning"),
            _document("client-contract", active),
            _document("sibling-contract", sibling),
            _document("foreign-contract", "foreign-company", customer_id=foreign.id, owner_id="foreign-owner"),
        ])
    return (client, factory, canvas, expert_id, requests), company, active


def _inventory(context: dict) -> dict[str, dict]:
    assert SOURCE_TEXT not in json.dumps(context)
    rows = context["available_documents"]
    assert all(set(row) == {"source_object_id", "filename", "workspace_id", "knowledge_status"} for row in rows)
    return {row["source_object_id"]: row for row in rows}


def _assert_initial_inventory(context: dict, company: str, active: str) -> None:
    rows = _inventory(context)
    assert rows == {
        "company-policy": {"source_object_id": "company-policy", "filename": "company-policy.txt",
                           "workspace_id": company, "knowledge_status": "ready"},
        "client-contract": {"source_object_id": "client-contract", "filename": "client-contract.txt",
                            "workspace_id": active, "knowledge_status": "ready"},
    }


async def _user_event(conversation, connection):
    client, _factory, canvas, _expert, _requests = conversation
    return await client.post(f"/workspace-chat/{canvas}/sessions/{connection['session_id']}/events",
        json={"event_key": "u1", "kind": "user", "text": "Vad säger company-policy.txt?"})


@pytest.mark.parametrize("mode", ["text", "voice"])
async def test_native_context_lists_company_and_active_client_without_canvas_sources(provider, user_token, mode):
    conversation, company, active = await _parent_canvas(provider, user_token)
    client, factory, canvas, _expert, _requests = conversation
    connection = await bootstrap(conversation, mode)
    _assert_initial_inventory(json.loads(connection["context"]), company, active)
    event = await _user_event(conversation, connection)
    assert event.status_code == 200, event.text
    _assert_initial_inventory(json.loads(event.json()["context"]), company, active)
    tool = await client.post(f"/workspace-chat/{canvas}/sessions/{connection['session_id']}/tools/get_workspace_context",
        json={"conversation_id": connection["conversation_id"], "agent_turn": 1,
              "turn_event_key": "u1", "arguments_json": "{}"})
    assert tool.status_code == 200, tool.text
    _assert_initial_inventory(tool.json()["workspace"], company, active)
    assert tool.json()["workspace"]["sources"] == []
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceSource)) == 0


def _external_gate(conversation, engine, boundary: str, monkeypatch):
    client, _factory, _canvas, _expert, _requests = conversation
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait():
        assert engine.pool.checkedout() == 0
        entered.set()
        await release.wait()

    class Memory(NoopExpertMemory):
        async def search(self, **_kwargs):
            if boundary != "provider":
                await wait()
            return []

    set_expert_memory_factory(Memory)
    dependencies = client._transport.app.dependency_overrides
    original = dependencies[get_elevenlabs_client]

    class WaitingClient(ElevenLabsAgentsClient):
        async def request(self, *args, **kwargs):
            if boundary == "provider":
                await wait()
            return await super().request(*args, **kwargs)

    async def dependency():
        async for native in original():
            yield WaitingClient(native.http)

    monkeypatch.setitem(dependencies, get_elevenlabs_client, dependency)
    return entered, release


async def _pending_request(conversation, mode: str, connection):
    if connection is not None:
        return await _user_event(conversation, connection)
    client, _factory, canvas, expert, _requests = conversation
    return await client.post(f"/workspace-chat/{canvas}/sessions", json={"expert_id": expert, "mode": mode})


async def _update_inventory(factory, company: str) -> None:
    async with factory.begin() as session:
        source = await session.get(StoredObject, "client-contract")
        source.knowledge_status = "failed"
        session.add(_document("new-company-policy", company, module="politik"))


@pytest.mark.parametrize("mode", ["text", "voice"])
@pytest.mark.parametrize("boundary", ["provider", "bootstrap_memory", "user_memory"])
async def test_inventory_refreshes_after_external_wait(single_connection_provider, user_token, monkeypatch, *, mode, boundary):
    original, engine = single_connection_provider
    conversation, company, _active = await _parent_canvas(original, user_token)
    connection = await bootstrap(conversation, mode) if boundary == "user_memory" else None
    entered, release = _external_gate(conversation, engine, boundary, monkeypatch)
    task = asyncio.create_task(_pending_request(conversation, mode, connection))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert engine.pool.checkedout() == 0
        await _update_inventory(conversation[1], company)
    finally:
        release.set()
        response = await task
    assert response.status_code == 200, response.text
    rows = _inventory(json.loads(response.json()["context"]))
    assert set(rows) == {"company-policy", "client-contract", "new-company-policy"}
    assert rows["client-contract"]["knowledge_status"] == "failed"
    assert rows["new-company-policy"]["workspace_id"] == company


@pytest.mark.parametrize("mode", ["text", "voice"])
@pytest.mark.parametrize("boundary", ["provider", "bootstrap_memory", "user_memory"])
async def test_revoked_parent_returns_no_inventory_after_external_wait(single_connection_provider, user_token, monkeypatch, *, mode, boundary):
    original, engine = single_connection_provider
    conversation, _company, active = await _parent_canvas(original, user_token)
    connection = await bootstrap(conversation, mode) if boundary == "user_memory" else None
    entered, release = _external_gate(conversation, engine, boundary, monkeypatch)
    task = asyncio.create_task(_pending_request(conversation, mode, connection))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert engine.pool.checkedout() == 0
        async with conversation[1].begin() as session:
            await session.execute(delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == active, WorkspaceMembership.user_id == USER_USER_ID))
    finally:
        release.set()
        response = await task
    assert response.status_code == 404, response.text
    assert "context" not in response.json() and "available_documents" not in response.json()
    assert "company-policy" not in response.text and "client-contract" not in response.text
