"""Private workspace facts stay owner scoped through the existing memory UI."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.database.models import Persona
from app.database.workspace_models import VoiceWorkspace
from app.database.workspaces import WorkspaceMembership
from app.services.workspaces import create_client_workspace
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expertgranskning.memory import ExpertMemoryHit, memory_user_id, set_expert_memory_factory
from app.services.live_voice_context import recent_voice_memories
from app.services.workspace_memory_context import workspace_memory_context
from app.services.workspace_memory_scope import workspace_memory_expert_id
from tests.conftest import ADMIN_USER_ID, USER_USER_ID
from tests.test_expert_memory import ListingMemory
from tests.test_workspace_conversations import (
    probe_connection,
    provider as provider,
    single_connection_provider as single_connection_provider,
)


def memory_hit(memory_id, expert_id, *, source="persona_chat", customer_id=1):
    return ExpertMemoryHit(id=memory_id, text="Fact " + memory_id, source=source,
        metadata={"user_id": memory_user_id(customer_id)}, user_id=memory_user_id(customer_id),
        expert_id=expert_id, created_at=datetime.now(UTC).isoformat())


class ProbingMemory(ListingMemory):
    def __init__(self, hits, *, connection_probe):
        super().__init__(hits)
        self.connection_probe = connection_probe
        self.gate = None

    async def check_connection(self):
        await self.connection_probe()
        if self.gate:
            gate, self.gate = self.gate, None
            await gate()

    async def list_all(self, **kwargs):
        await self.check_connection()
        return await super().list_all(**kwargs)

    async def list_for_customer(self, **kwargs):
        await self.check_connection()
        return await super().list_for_customer(**kwargs)

    async def get(self, **kwargs):
        await self.check_connection()
        return await super().get(**kwargs)

    async def update(self, **kwargs):
        await self.check_connection()
        return await super().update(**kwargs)

    async def delete(self, **kwargs):
        await self.check_connection()
        await super().delete(**kwargs)

    async def delete_all(self, **_kwargs):
        raise AssertionError("An unscoped clear can erase another workspace owner's facts")


@pytest.fixture
async def private_memory_store(single_connection_provider):
    conversation, engine = single_connection_provider
    client, factory, workspace_id, expert_id, _ = conversation
    async with factory() as db:
        persona = await db.get(Persona, expert_id)
        workspace = await db.get(VoiceWorkspace, workspace_id)
        shared_key = persona_catalog_key(persona)
        own_key = workspace_memory_expert_id(persona, ADMIN_USER_ID, workspace_parent_id=workspace.workspace_id)
        other_key = workspace_memory_expert_id(persona, USER_USER_ID, workspace_parent_id=workspace.workspace_id)
        name = persona.name
    async def probe():
        assert engine.pool.checkedout() == 0
        await probe_connection(factory, workspace_id)
    hits = [memory_hit("public", shared_key), memory_hit("own", own_key, source="workspace_chat"),
            memory_hit("other", other_key, source="workspace_chat"),
            memory_hit("private-source", shared_key, source="workspace_chat"),
            memory_hit("private-marker", other_key, source="expert_consult")]
    memory = ProbingMemory(hits, connection_probe=probe)
    set_expert_memory_factory(lambda: memory)
    return client, memory, conversation, name


@pytest.mark.asyncio
async def test_persona_memories_show_and_edit_only_current_owner(private_memory_store, user_token):
    client, memory, conversation, name = private_memory_store
    url = f"/personas/{conversation[3]}/memories"
    rows = (await client.get(url)).json()["memories"]
    assert {row["id"] for row in rows} == {"public", "own"}
    assert all(row["expert_name"] == name and row["persona_id"] == conversation[3] for row in rows)
    updated = await client.patch(url + "/own", json={"text": "Own revised fact"})
    assert updated.status_code == 200 and updated.json()["expert_name"] == name
    for method in ("PATCH", "DELETE"):
        args = {"json": {"text": "Forbidden"}} if method == "PATCH" else {}
        denied = await client.request(method, url + "/other", **args)
        assert denied.status_code == 404
    rows = (await client.get(url, headers={"Authorization": "Bearer " + user_token})).json()["memories"]
    assert {row["id"] for row in rows} == {"public", "other", "private-marker"}
    assert (await client.delete(url + "/own")).status_code == 204
    assert "other" in {hit.id for hit in memory.hits}


@pytest.mark.asyncio
async def test_admin_memory_never_lists_changes_or_clears_private_facts(private_memory_store):
    client, memory, _, _ = private_memory_store
    listed = await client.get("/expert-memory")
    assert listed.status_code == 200
    assert {row["id"] for row in listed.json()["memories"]} == {"public"}
    for memory_id in ("own", "other", "private-source", "private-marker"):
        assert (await client.patch("/expert-memory/" + memory_id, json={"text": "Forbidden"})).status_code == 404
        assert (await client.delete("/expert-memory/" + memory_id)).status_code == 404
    assert (await client.delete("/expert-memory")).status_code == 204
    assert {hit.id for hit in memory.hits} == {"own", "other", "private-source", "private-marker"}


@pytest.mark.asyncio
async def test_clear_persona_removes_shared_and_own_private_only(private_memory_store):
    client, memory, conversation, _ = private_memory_store
    cleared = await client.delete(f"/personas/{conversation[3]}/memories")
    assert cleared.status_code == 204
    assert {hit.id for hit in memory.hits} == {"other", "private-source", "private-marker"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "surface"), [("GET", "persona"), ("PATCH", "persona"),
    ("DELETE", "persona"), ("DELETE", "persona_all"), ("GET", "admin"),
    ("PATCH", "admin"), ("DELETE", "admin"), ("DELETE", "admin_all")])
async def test_memory_api_releases_single_connection_while_mem0_pending(private_memory_store, method, surface):
    client, memory, conversation, _ = private_memory_store
    entered, release = asyncio.Event(), asyncio.Event()
    async def gate():
        entered.set()
        await release.wait()
    memory.gate = gate
    url = f"/personas/{conversation[3]}/memories" if surface.startswith("persona") else "/expert-memory"
    if method in {"PATCH", "DELETE"} and not surface.endswith("all"):
        url += "/public"
    args = {"json": {"text": "Changed"}} if method == "PATCH" else {}
    task = asyncio.create_task(client.request(method, url, **args))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await memory.connection_probe()
    finally:
        release.set()
    response = await task
    assert response.status_code in {200, 204}, response.text


def test_legacy_voice_summary_excludes_private_source_and_namespace():
    hits = [memory_hit("public", "expert"), memory_hit("private", "expert", source="workspace_chat"),
            memory_hit("namespace", "expert:workspace-owner:owner", source="expert_consult")]
    assert [hit.id for hit in recent_voice_memories(hits, now=datetime.now(UTC))] == ["public"]


@pytest.mark.asyncio
async def test_workspace_context_does_not_accept_foreign_namespace(monkeypatch):
    persona = Persona(id="exp_1_legal", customer_id=1, name="Legal", kind="expert", profile={})
    own_key = workspace_memory_expert_id(persona, ADMIN_USER_ID, workspace_parent_id="parent-one")
    other_key = workspace_memory_expert_id(persona, USER_USER_ID, workspace_parent_id="parent-one")
    class Memory(ListingMemory):
        async def search(self, **kwargs):
            if kwargs["expert_id"] == "legal":
                assert "workspace_chat" not in kwargs["sources"]
                return [memory_hit("public", "legal")]
            return self.hits
    sibling_key = workspace_memory_expert_id(persona, ADMIN_USER_ID, workspace_parent_id="parent-two")
    memory = Memory([memory_hit("own", own_key, source="workspace_chat"),
        memory_hit("sibling", sibling_key, source="workspace_chat"),
        memory_hit("foreign", other_key, source="workspace_chat"),
        memory_hit("wrong-customer", own_key, source="workspace_chat", customer_id=2)])
    set_expert_memory_factory(lambda: memory)
    context = await workspace_memory_context(persona, "this", {"chat.expert.memory": "{memories}"}, owner_id=ADMIN_USER_ID, workspace_parent_id="parent-one")
    assert "Fact public" in context and "Fact own" in context
    assert "Fact foreign" not in context and "Fact wrong-customer" not in context and "Fact sibling" not in context


@pytest.mark.asyncio
async def test_private_memories_follow_current_parent_membership(private_memory_store, user_token):
    client, memory, conversation, _name = private_memory_store
    async with conversation[1]() as session:
        persona = await session.get(Persona, conversation[3])
        first = await create_client_workspace(session, customer_id=1, user_id=USER_USER_ID, name="Client A")
        second = await create_client_workspace(session, customer_id=1, user_id=USER_USER_ID, name="Client B")
        memory.hits.extend([
            memory_hit("client-a", workspace_memory_expert_id(persona, USER_USER_ID, workspace_parent_id=first.id), source="workspace_chat"),
            memory_hit("client-b", workspace_memory_expert_id(persona, USER_USER_ID, workspace_parent_id=second.id), source="workspace_chat"),
        ])
        first_id, second_id = first.id, second.id
        await session.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == second_id))
        await session.commit()
    client.headers["Authorization"] = "Bearer " + user_token
    url = f"/personas/{conversation[3]}/memories"
    before = {row["id"] for row in (await client.get(url)).json()["memories"]}
    assert "client-a" in before and "client-b" not in before
    async with conversation[1]() as session:
        await session.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == first_id))
        await session.commit()
    after = {row["id"] for row in (await client.get(url)).json()["memories"]}
    assert not {"client-a", "client-b"} & after
    for method in ("PATCH", "DELETE"):
        kwargs = {"json": {"text": "Forbidden"}} if method == "PATCH" else {}
        assert (await client.request(method, url + "/client-a", **kwargs)).status_code == 404
    assert (await client.delete(url)).status_code == 204
    assert {"client-a", "client-b", "own"} <= {hit.id for hit in memory.hits}


def test_private_memory_namespace_requires_parent():
    persona = Persona(id="expert", customer_id=1, name="Expert", kind="expert", profile={})
    with pytest.raises(ValueError, match="parent"):
        workspace_memory_expert_id(persona, "owner", workspace_parent_id="")
    assert workspace_memory_expert_id(persona, "owner", workspace_parent_id="a") != workspace_memory_expert_id(persona, "owner", workspace_parent_id="b")
