"""Voice canvases preserve main workspace sharing while keeping chats private."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database.models import Job, Persona, StoredObject
from app.database.workspace_models import WorkspaceOperation, WorkspaceResearch
from app.database.workspaces import WorkspaceChat, WorkspaceMembership
from app.services import jobs
from tests.conftest import USER_USER_ID


@pytest.fixture(autouse=True)
def hold_jobs(monkeypatch):
    monkeypatch.setattr(jobs, "enqueue_job", lambda _job_id: None)


async def create_voice(client, *, parent=None, chat=None, headers=None, key=None):
    response = await client.post("/voice-workspaces?customer_id=1", headers=headers,
        json={"title": "Private canvas", "workspace_id": parent, "chat_id": chat,
              "idempotency_key": key or str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


async def source_upload(client, canvas):
    response = await client.post(f"/voice-workspaces/{canvas['id']}/sources/upload",
        data={"idempotency_key": str(uuid4())}, files={"file": ("shared.txt", b"A cited source", "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()["source_id"]


@pytest.mark.asyncio
async def test_binding_replay_keeps_one_private_core_chat(client_db):
    client, factory = client_db
    first = await create_voice(client, key="same-create")
    assert await create_voice(client, key="same-create") == first
    assert (await create_voice(client, parent=first["workspace_id"], chat=first["chat_id"]))["id"] == first["id"]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceChat)) == 1
        chat = await session.get(WorkspaceChat, first["chat_id"])
        assert chat.workspace_id == first["workspace_id"] and chat.persona_id is None


@pytest.mark.asyncio
async def test_shared_member_source_allowed_cross_client_and_revoked_member_denied(client_db, user_token):
    client, factory = client_db
    headers = {"Authorization": f"Bearer {user_token}"}
    parent = (await client.post("/workspaces", headers=headers, json={"name": "Selected client"})).json()["id"]
    private = await create_voice(client, parent=parent, headers=headers)
    colleague = await create_voice(client, parent=parent)
    source = await source_upload(client, colleague)
    response = await client.post(f"/voice-workspaces/{private['id']}/sources", headers=headers,
        json={"source_id": source, "idempotency_key": "shared-attach"})
    assert response.status_code == 200
    assert (await client.get(f"/voice-workspaces/{private['id']}/sources/{source}/file", headers=headers)).status_code == 200
    assert (await client.get(f"/voice-workspaces/{private['id']}")).status_code == 404
    other_parent = (await client.post("/workspaces?customer_id=1", json={"name": "Other client"})).json()["id"]
    other = await create_voice(client, parent=other_parent)
    other_source = await source_upload(client, other)
    forbidden = await client.post(f"/voice-workspaces/{private['id']}/sources", headers=headers,
        json={"source_id": other_source, "idempotency_key": "other-client"})
    assert forbidden.status_code == 404
    async with factory() as session:
        row = await session.get(StoredObject, source)
        assert row.workspace_id == parent
        await session.delete(await session.get(WorkspaceMembership, (parent, USER_USER_ID)))
        await session.commit()
    assert (await client.get(f"/voice-workspaces/{private['id']}", headers=headers)).status_code == 404
    assert (await client.get(f"/voice-workspaces/{private['id']}/sources/{source}/file", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_research_job_is_persistent_before_attempt_and_links_only_its_scope(client_db):
    client, factory = client_db
    canvas = await create_voice(client)
    async with factory() as session:
        expert = await session.scalar(select(Persona).where(Persona.customer_id == 1, Persona.kind == "expert").limit(1))
        expert.tools = ["start_research"]
        expert_id = expert.id
        await session.commit()
    selected = await client.patch(f"/voice-workspaces/{canvas['id']}", json={"expected_revision": 0,
        "idempotency_key": "expert", "state": {**canvas["state"], "expert_id": expert_id}})
    assert selected.status_code == 200
    queued = await client.post(f"/voice-workspaces/{canvas['id']}/tools/start_research", json={
        "idempotency_key": "research", "arguments": {"objective": "A research question", "confirmed": True,
                                                        "source_object_ids": []}})
    assert queued.status_code == 200, queued.text
    result = queued.json()
    assert result["job_id"] and result["attempt_id"] is None and result["run_id"] is None
    waiting = (await client.get(f"/voice-workspaces/{canvas['id']}")).json()["research"]
    assert waiting[0]["job_id"] == result["job_id"] and waiting[0]["attempt_id"] is None
    async with factory() as session:
        from app.services.execution.service import create_attempt, create_run
        operation = await session.get(WorkspaceOperation, result["operation_id"])
        job = await session.get(Job, operation.job_id)
        assert job.request["workspace_id"] == canvas["workspace_id"] and job.request["chat_id"] == canvas["chat_id"]
        assert job.request["voice_workspace_id"] == canvas["id"]
        run = await create_run(session, customer_id=1, module="dd", title="Research",
                               context={**job.request, "job_id": job.id})
        attempt = await create_attempt(session, run_id=run.id, attempt_type="workspace_research", input_snapshot={})
        job.result = {"run_id": run.id, "attempt_id": attempt.id}
        attempt_id = attempt.id
        await session.commit()
    finished = await client.get(f"/voice-workspaces/{canvas['id']}")
    assert finished.status_code == 200 and finished.json()["research"][0]["attempt_id"] == attempt_id
    async with factory() as session:
        assert await session.get(WorkspaceResearch, (canvas["id"], attempt_id)) is not None
