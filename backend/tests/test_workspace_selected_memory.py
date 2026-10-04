"""The selected client memory view cannot read or clear sibling-client facts."""

import asyncio

import pytest
from sqlalchemy import delete

from app.database.models import Persona
from app.database.workspaces import WorkspaceMembership
from app.services.workspaces import create_client_workspace
from app.services.workspace_memory_scope import workspace_memory_expert_id
from tests.conftest import USER_USER_ID
from tests.test_workspace_memory_policy import (
    memory_hit,
    private_memory_store as private_memory_store,
    provider as provider,
    single_connection_provider as single_connection_provider,
)


@pytest.fixture
async def selected_memories(private_memory_store, user_token):
    client, memory, conversation, _name = private_memory_store
    async with conversation[1]() as session:
        persona = await session.get(Persona, conversation[3])
        parents = [await create_client_workspace(session, customer_id=1, user_id=USER_USER_ID, name=name)
                   for name in ("Client A", "Client B")]
        for index, parent in enumerate(parents):
            key = workspace_memory_expert_id(persona, USER_USER_ID, workspace_parent_id=parent.id)
            memory.hits.append(memory_hit("client-" + str(index), key, source="workspace_chat"))
        ids = [parent.id for parent in parents]
        await session.commit()
    client.headers["Authorization"] = "Bearer " + user_token
    return client, memory, conversation, ids


async def test_selected_parent_lists_edits_and_clears_only_own_namespace(selected_memories):
    client, memory, conversation, parents = selected_memories
    base = f"/personas/{conversation[3]}/memories"
    query = {"workspace_id": parents[0]}
    listed = await client.get(base, params=query)
    assert listed.status_code == 200 and {row["id"] for row in listed.json()["memories"]} == {"public", "client-0"}
    assert (await client.patch(base + "/client-0", params=query, json={"text": "Updated selected fact"})).status_code == 200
    for method in ("PATCH", "DELETE"):
        kwargs = {"json": {"text": "Forbidden"}} if method == "PATCH" else {}
        assert (await client.request(method, base + "/client-1", params=query, **kwargs)).status_code == 404
    assert (await client.delete(base, params=query)).status_code == 204
    assert {"client-1", "other", "own"} <= {hit.id for hit in memory.hits}
    assert not {"client-0", "public"} & {hit.id for hit in memory.hits}
    legacy = await client.get(base)
    assert {row["id"] for row in legacy.json()["memories"]} == {"client-1", "other", "private-marker"}


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE", "CLEAR"])
async def test_selected_parent_membership_rechecked_after_mem0_lookup(selected_memories, method):
    client, memory, conversation, parents = selected_memories
    entered, release = asyncio.Event(), asyncio.Event()
    async def gate():
        entered.set()
        await release.wait()
    memory.gate = gate
    base = f"/personas/{conversation[3]}/memories"
    url = base if method in {"GET", "CLEAR"} else base + "/client-0"
    actual_method = "DELETE" if method == "CLEAR" else method
    kwargs = {"json": {"text": "Forbidden update"}} if method == "PATCH" else {}
    task = asyncio.create_task(client.request(actual_method, url, params={"workspace_id": parents[0]}, **kwargs))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with conversation[1]() as session:
            await session.execute(delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == parents[0], WorkspaceMembership.user_id == USER_USER_ID))
            await session.commit()
        release.set()
        response = await task
        assert response.status_code == 404, response.text
        assert next(hit.text for hit in memory.hits if hit.id == "client-0") == "Fact client-0"
        assert "public" in {hit.id for hit in memory.hits}
    finally:
        release.set()
        if not task.done():
            await task


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE", "CLEAR"])
async def test_inaccessible_selected_parent_is_denied_before_mem0(selected_memories, method):
    client, memory, conversation, parents = selected_memories
    async with conversation[1]() as session:
        await session.execute(delete(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == parents[0], WorkspaceMembership.user_id == USER_USER_ID))
        await session.commit()
    async def forbidden():
        raise AssertionError("Inaccessible workspace reached Mem0")
    memory.connection_probe = forbidden
    base = f"/personas/{conversation[3]}/memories"
    url = base if method in {"GET", "CLEAR"} else base + "/client-0"
    kwargs = {"json": {"text": "Forbidden update"}} if method == "PATCH" else {}
    response = await client.request("DELETE" if method == "CLEAR" else method, url,
        params={"workspace_id": parents[0]}, **kwargs)
    assert response.status_code == 404
