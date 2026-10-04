"""A driver with unknown rowcount must still execute idempotent writes and CAS."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.database.workspace_models import WorkspaceArtifact, WorkspaceOperation
from app.services.workspace.service import new_id, publish_artifact_revision
from tests.test_voice_workspaces import workspace


class UnknownCountResult:
    rowcount = -1

    def __init__(self, result):
        self.result = result

    def __getattr__(self, name):
        return getattr(self.result, name)


@pytest.fixture
def unknown_rowcount(monkeypatch):
    original = AsyncSession.execute

    async def execute(session, statement, *args, **kwargs):
        result = await original(session, statement, *args, **kwargs)
        if getattr(statement, "is_insert", False) or getattr(statement, "is_update", False):
            return UnknownCountResult(result)
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute)


@pytest.mark.asyncio
async def test_expert_selection_returns_full_state_and_replays_with_unknown_rowcount(client_db, unknown_rowcount):
    client, factory = client_db
    canvas = await workspace(client)
    async with factory() as session:
        expert_id = await session.scalar(select(Persona.id).where(Persona.customer_id == 1, Persona.kind == "expert").limit(1))
    payload = {"expected_revision": 0, "idempotency_key": "expert-selection",
               "state": {**canvas["state"], "expert_id": expert_id}}
    updated = await client.patch(f"/voice-workspaces/{canvas['id']}", json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["state"]["expert_id"] == expert_id and updated.json()["revision"] == 1
    assert (await client.patch(f"/voice-workspaces/{canvas['id']}", json=payload)).json() == updated.json()
    conflict = await client.patch(f"/voice-workspaces/{canvas['id']}", json={**payload, "idempotency_key": "stale"})
    assert conflict.status_code == 409
    async with factory() as session:
        operation = await session.scalar(select(WorkspaceOperation).where(WorkspaceOperation.workspace_id == canvas["id"]))
        assert operation.status == "completed" and operation.result["state"]["expert_id"] == expert_id


@pytest.mark.asyncio
async def test_artifact_revision_cas_and_immutable_snapshot_with_unknown_rowcount(client_db, unknown_rowcount):
    client, factory = client_db
    canvas = await workspace(client)
    async with factory() as session:
        artifact = WorkspaceArtifact(id=new_id(), workspace_id=canvas["id"], kind="document", title="Draft",
                                     status="queued", revision=0, content={})
        session.add(artifact)
        await session.flush()
        await publish_artifact_revision(session, artifact, expected_revision=0,
            content={"blocks": [{"id": "p1", "type": "paragraph", "text": "Original", "source_refs": []}]})
        artifact_id = artifact.id
        await session.commit()
    body = {"expected_revision": 1, "idempotency_key": "edit", "content": {
        "blocks": [{"id": "p1", "type": "paragraph", "text": "Edited", "source_refs": []}]}}
    edited = await client.patch(f"/voice-workspaces/{canvas['id']}/artifacts/{artifact_id}", json=body)
    assert edited.status_code == 200 and edited.json()["artifact"]["revision"] == 2
    stale = await client.patch(f"/voice-workspaces/{canvas['id']}/artifacts/{artifact_id}", json={**body, "idempotency_key": "stale"})
    assert stale.status_code == 409
    previous = await client.get(f"/voice-workspaces/{canvas['id']}/artifacts/{artifact_id}/revisions/1")
    assert previous.json()["content"]["blocks"][0]["text"] == "Original"
