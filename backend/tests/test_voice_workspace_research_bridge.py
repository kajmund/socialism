"""Native research uses the same manifest and durable job as the core chat."""

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.database.models import Job, Persona, StoredObject, UserAccount
from app.database.workspace_models import WorkspaceOperation
from app.database.workspaces import WorkspaceChatMessage, WorkspaceMembership
from app.schemas.workspace import WorkspaceState
from app.services.workspace.containers import WorkspaceContainer
from app.services.workspace.service import add_source, create_workspace
from app.services.workspace.tools import execute_workspace_tool
from tests.test_workspace_document_grounding import documents as documents


@pytest.fixture
async def research_canvas(documents):
    factory, _store, _embeddings, (_company, parent, _sibling) = documents
    async with factory() as session:
        user = await session.get(UserAccount, "workspace-user")
        expert = Persona(id="research-expert", customer_id=1, kind="expert", name="Research expert", occ="Lawyer",
            district="", profile={}, tools=["start_research"])
        session.add(expert)
        canvas = await create_workspace(session, user, title="Voice research", module="expertgranskning",
            container=WorkspaceContainer(workspace_id=parent))
        canvas.state = WorkspaceState(expert_id=expert.id, documents=[{"source_id": "source-1"}]).model_dump()
        for source_id in ("source-0", "source-1", "source-2"):
            source = await session.get(StoredObject, source_id)
            source.knowledge_status = "ready"
        await add_source(session, canvas, "source-1")
        identities = canvas.id, canvas.workspace_id, canvas.chat_id
        await session.commit()
    return factory, identities


async def dispatch(factory, canvas_id, *, selected=None, key="research"):
    async with factory() as session:
        user = await session.get(UserAccount, "workspace-user")
        arguments = {"objective": "Research the contract", "confirmed": True}
        if selected is not None:
            arguments["source_object_ids"] = selected
        result = await execute_workspace_tool(session, workspace_id=canvas_id, user=user, tool_name="start_research",
            arguments=arguments, idempotency_key=key)
        await session.commit()
        return result


@pytest.mark.parametrize("explicit", [False, True])
async def test_research_freezes_parent_chat_and_exact_document_manifest(research_canvas, explicit):
    factory, (canvas_id, parent, chat_id) = research_canvas
    result = await dispatch(factory, canvas_id, selected=[] if explicit else None)
    replay = await dispatch(factory, canvas_id, selected=[] if explicit else None)
    assert result == replay and result["status"] == "queued"
    assert result["run_id"] is None and result["attempt_id"] is None
    async with factory() as session:
        job = await session.get(Job, result["job_id"])
        request = job.request
        assert job.kind == "workspace_research"
        assert request["workspace_id"] == parent and request["chat_id"] == chat_id
        assert request["voice_workspace_id"] == canvas_id and request["owner_user_id"] == "workspace-user"
        assert request["readable_workspace_ids"][-1] == parent and request["entrypoint"] == "tool"
        manifest = request["document_manifest"]
        assert [row["source_object_id"] for row in manifest] == ([] if explicit else ["source-1"])
        assert all(row["document_version_id"] and row["workspace_id"] == parent for row in manifest)
        assert await session.scalar(select(func.count()).select_from(Job)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkspaceChatMessage)) == 1
        operation = await session.get(WorkspaceOperation, result["operation_id"])
        assert operation.job_id == job.id


async def test_research_rejects_sibling_source_and_revoked_parent_membership(research_canvas):
    factory, (canvas_id, parent, _chat_id) = research_canvas
    with pytest.raises(HTTPException) as error:
        await dispatch(factory, canvas_id, selected=["source-2"], key="sibling")
    assert error.value.status_code == 404
    async with factory() as session:
        member = await session.get(WorkspaceMembership, (parent, "workspace-user"))
        await session.delete(member)
        await session.commit()
    with pytest.raises(HTTPException) as error:
        await dispatch(factory, canvas_id, selected=[], key="revoked")
    assert error.value.status_code == 404
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 0
