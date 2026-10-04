"""Private sessions lose access when a client-workspace membership is revoked."""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text

from app.database.models import Job, Persona
from app.database.workspace_models import VoiceWorkspace
from app.services import jobs
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspaces import WorkspaceMembership
from app.services.expertgranskning.memory import set_expert_memory_factory
from tests.conftest import NoopExpertMemory, USER_USER_ID
from tests.test_workspace_conversations import (
    bootstrap,
    provider as provider,
    single_connection_provider as single_connection_provider,
)


@pytest.mark.parametrize("phase", ["bootstrap", "user_context"])
async def test_provider_rechecks_parent_membership_after_external_memory(single_connection_provider, user_token, phase):
    original, engine = single_connection_provider
    client, factory, _old_canvas, expert_id, requests = original
    client.headers["Authorization"] = "Bearer " + user_token
    parent = (await client.post("/workspaces", json={"name": "Private client"})).json()["id"]
    response = await client.post("/voice-workspaces", json={"workspace_id": parent, "title": "Private voice",
        "idempotency_key": str(uuid4())})
    assert response.status_code == 201, response.text
    canvas = response.json()["id"]
    conversation = client, factory, canvas, expert_id, requests
    connection = await bootstrap(conversation) if phase == "user_context" else None
    entered, release = asyncio.Event(), asyncio.Event()

    class Memory(NoopExpertMemory):
        async def search(self, **_kwargs):
            assert engine.pool.checkedout() == 0
            entered.set()
            await release.wait()
            return []

    set_expert_memory_factory(Memory)
    if connection:
        url = f"/workspace-chat/{canvas}/sessions/{connection['session_id']}/events"
        payload = {"event_key": "u1", "kind": "user", "text": "Private document question"}
    else:
        url = f"/workspace-chat/{canvas}/sessions"
        payload = {"expert_id": expert_id, "mode": "text"}
    task = asyncio.create_task(client.post(url, json=payload))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with factory() as other:
            await other.execute(delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == parent, WorkspaceMembership.user_id == USER_USER_ID))
            await other.commit()
        release.set()
        response = await task
        assert response.status_code == 404 and "context" not in response.json(), response.text
        history = await client.get(f"/workspace-chat/{canvas}/threads/{expert_id}/messages")
        assert history.status_code == 404
        if phase == "bootstrap":
            async with factory() as other:
                rows = list(await other.scalars(select(WorkspaceConversationSession).where(
                    WorkspaceConversationSession.workspace_id == canvas)))
                assert len(rows) == 1 and rows[0].status == "failed"
    finally:
        release.set()
        if not task.done():
            await task


@pytest.mark.parametrize("confirmed_by_user", [False, True])
async def test_native_research_requires_persisted_confirmation_and_queues_core_job(provider, monkeypatch, confirmed_by_user):
    client, factory, canvas_id, expert_id, _requests = provider
    async with factory() as session:
        expert = await session.get(Persona, expert_id)
        expert.tools = ["start_research"]
        await session.commit()
    connection = await bootstrap(provider, "text")
    events = f"/workspace-chat/{canvas_id}/sessions/{connection['session_id']}/events"
    assert (await client.post(events, json={"event_key": "offer", "kind": "agent",
        "text": "Vill du att jag startar research?"})).status_code == 200
    assert (await client.post(events, json={"event_key": "confirmation", "kind": "user",
        "text": "Ja starta research" if confirmed_by_user else "Visa dokumentet"})).status_code == 200
    scheduled = []
    monkeypatch.setattr(jobs, "enqueue_job", scheduled.append)
    url = f"/workspace-chat/{canvas_id}/sessions/{connection['session_id']}/tools/start_research"
    body = {"conversation_id": connection["conversation_id"], "agent_turn": 1, "turn_event_key": "confirmation",
        "arguments_json": json.dumps({"objective": "Research public sources", "confirmed": True, "source_object_ids": []})}
    response = await client.post(url, json=body)
    if not confirmed_by_user:
        assert response.status_code == 409 and not scheduled
    else:
        assert response.status_code == 200, response.text
        result = response.json()
        replay = await client.post(url, json=body)
        assert replay.json() == result and scheduled == [result["job_id"], result["job_id"]]
        async with factory() as session:
            job = await session.get(Job, result["job_id"])
            canvas = await session.get(VoiceWorkspace, canvas_id)
            assert job.request["workspace_id"] == canvas.workspace_id and job.request["chat_id"] == canvas.chat_id
            assert job.request["voice_workspace_id"] == canvas_id and job.request["document_manifest"] == []
            assert len(list(await session.scalars(select(Job)))) == 1


async def test_bootstrap_persists_parent_before_initial_event_with_foreign_keys(single_connection_provider):
    conversation, engine = single_connection_provider
    async with engine.connect() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
    result = await bootstrap(conversation, "text")
    async with conversation[1]() as session:
        parent = await session.get(WorkspaceConversationSession, result["session_id"])
        initial = await session.scalar(select(WorkspaceConversationEvent).where(
            WorkspaceConversationEvent.session_id == result["session_id"], WorkspaceConversationEvent.kind == "init"))
        assert parent.status == "active" and initial is not None
        assert initial.payload["workspace_state"]["expert_id"] == parent.expert_id
