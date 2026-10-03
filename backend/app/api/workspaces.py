"""Authenticated workspace commands shared by clicks, text and live voice."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import customer_id_for_user
from app.database.models import UserAccount
from app.database.session import get_session
from app.database.workspace_models import Workspace, WorkspaceArtifactRevision, WorkspaceOperation, WorkspaceSource
from app.schemas.workspace import WorkspaceArtifactPatch, WorkspaceCreate, WorkspacePatch, WorkspaceSourceAdd, WorkspaceToolRequest
from app.services import jobs as jobs_service
from app.services.object_storage import MAX_UNDERLAG_BYTES
from app.services.workspace.service import (
    accept_operation, artifact_out, create_workspace, fingerprint, patch_workspace,
    require_artifact, require_workspace, workspace_out,
)
from app.services.workspace.sources import read_reference
from app.services.workspace.tools import execute_workspace_tool
from app.services.workspace.ingest import UploadInput, ingest

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


async def _commit_and_schedule(session: AsyncSession, result: dict) -> None:
    await session.commit()
    if result.get("status") == "queued" and result.get("job_id"):
        jobs_service.enqueue_job(result["job_id"])


@router.get("")
async def list_workspaces(*, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> list[dict]:
    customer_id = await customer_id_for_user(session, user)
    rows = list((await session.execute(select(Workspace).where(Workspace.owner_user_id == user.id,
        Workspace.customer_id == customer_id).order_by(Workspace.updated_at.desc()).limit(100))).scalars())
    return [{"id": row.id, "title": row.title, "module": row.module, "revision": row.revision, "state": row.state} for row in rows]


@router.post("", status_code=201)
async def post_workspace(body: WorkspaceCreate, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    workspace = await create_workspace(session, user, title=body.title, module=body.module, idempotency_key=body.idempotency_key, language=body.language)
    await session.commit()
    return await workspace_out(session, workspace)


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    return await workspace_out(session, await require_workspace(session, workspace_id, user))


@router.patch("/{workspace_id}")
async def update_workspace(workspace_id: str, body: WorkspacePatch, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    operation, accepted = await accept_operation(session, workspace, tool_name="update_workspace", arguments=body.model_dump(exclude={"idempotency_key", "expected_revision"}),
        expected_revision=body.expected_revision, idempotency_key=body.idempotency_key)
    if not accepted:
        return operation.result
    await patch_workspace(session, workspace, expected_revision=body.expected_revision, state=body.state, title=body.title)
    result = await workspace_out(session, workspace)
    operation.result, operation.status = result, "completed"
    await session.commit()
    return result


@router.post("/{workspace_id}/sources")
async def post_workspace_source(workspace_id: str, body: WorkspaceSourceAdd, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    result = await execute_workspace_tool(session, workspace_id=workspace_id, user=user, tool_name="ingest_source",
        arguments={"source_id": body.source_id}, idempotency_key=body.idempotency_key)
    await session.commit()
    return result


@router.post("/{workspace_id}/sources/upload", status_code=201)
async def upload_workspace_source(workspace_id: str, idempotency_key: str = Form(...), file: UploadFile = File(...),
                                  *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    raw = await file.read(MAX_UNDERLAG_BYTES + 1)
    operation, accepted = await accept_operation(session, workspace, tool_name="upload_source", idempotency_key=idempotency_key,
        arguments={"filename": file.filename, "content_type": file.content_type, "content_hash": fingerprint(raw.hex())})
    if not accepted:
        return operation.result
    await ingest(session, workspace, operation, upload=UploadInput(raw, file.filename or "file", file.content_type or "application/octet-stream"))
    await _commit_and_schedule(session, operation.result)
    return operation.result


@router.delete("/{workspace_id}/sources/{source_id}")
async def remove_workspace_source(workspace_id: str, source_id: str, idempotency_key: str = Query(..., min_length=1, max_length=160),
                                   *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    operation, accepted = await accept_operation(session, workspace, tool_name="remove_source", arguments={"source_id": source_id}, idempotency_key=idempotency_key)
    if not accepted:
        return operation.result
    await session.execute(delete(WorkspaceSource).where(WorkspaceSource.workspace_id == workspace.id, WorkspaceSource.source_id == source_id))
    from app.schemas.workspace import WorkspaceState
    state = WorkspaceState.model_validate(workspace.state)
    state.documents = [tab for tab in state.documents if tab.source_id != source_id]
    state.split_source_ids = [value for value in state.split_source_ids if value != source_id]
    if state.selection and (state.selection.source_id == source_id or state.selection.reference_id):
        state.selection = None
    await patch_workspace(session, workspace, expected_revision=workspace.revision, state=state)
    operation.result, operation.status = {"status": "completed", "source_id": source_id}, "completed"
    await session.commit()
    return operation.result


@router.get("/{workspace_id}/references/{reference_id}")
async def get_workspace_reference(workspace_id: str, reference_id: str, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    return await read_reference(session, await require_workspace(session, workspace_id, user), reference_id)


@router.post("/{workspace_id}/tools/{tool_name}")
async def workspace_tool(workspace_id: str, tool_name: str, body: WorkspaceToolRequest, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    if body.expected_revision is not None:
        workspace = await require_workspace(session, workspace_id, user)
        existing = await session.scalar(select(WorkspaceOperation.id).where(
            WorkspaceOperation.workspace_id == workspace_id, WorkspaceOperation.idempotency_key == body.idempotency_key))
        if existing is None and workspace.revision != body.expected_revision:
            raise HTTPException(status_code=409, detail="workspace_revision_conflict")
    result = await execute_workspace_tool(session, workspace_id=workspace_id, user=user, tool_name=tool_name,
        arguments=body.arguments, idempotency_key=body.idempotency_key)
    await _commit_and_schedule(session, result)
    return result


@router.get("/{workspace_id}/artifacts/{artifact_id}")
async def get_workspace_artifact(workspace_id: str, artifact_id: str, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    return artifact_out(await require_artifact(session, workspace, artifact_id))


@router.get("/{workspace_id}/artifacts/{artifact_id}/revisions/{revision}")
async def get_workspace_artifact_revision(workspace_id: str, artifact_id: str, revision: int, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    await require_artifact(session, workspace, artifact_id)
    row = await session.get(WorkspaceArtifactRevision, (artifact_id, revision))
    if row is None:
        raise HTTPException(status_code=404, detail="artifact_revision_not_found")
    return {"artifact_id": artifact_id, "revision": row.revision, "title": row.title, "content": row.content}


@router.patch("/{workspace_id}/artifacts/{artifact_id}")
async def update_workspace_artifact(workspace_id: str, artifact_id: str, body: WorkspaceArtifactPatch, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    result = await execute_workspace_tool(session, workspace_id=workspace_id, user=user, tool_name="revise_document",
        arguments={"artifact_id": artifact_id, "expected_revision": body.expected_revision, "content": body.content, "title": body.title},
        idempotency_key=body.idempotency_key)
    await session.commit()
    return result
