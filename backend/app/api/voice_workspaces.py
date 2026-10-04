"""Authenticated workspace commands shared by clicks, text and live voice."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.database.session import get_session
from app.database.transaction_state import has_pending_writes
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifactRevision, WorkspaceOperation, WorkspaceSource
from app.schemas.workspace import WorkspaceArtifactPatch, WorkspaceCreate, WorkspacePatch, WorkspaceSourceAdd, WorkspaceToolRequest
from app.services import jobs as jobs_service
from app.services.object_storage import MAX_UNDERLAG_BYTES
from app.services.workspace.service import (
    accept_operation, artifact_out, create_workspace, fingerprint, patch_workspace,
    require_artifact, require_workspace, workspace_out,
)
from app.services.workspace.sources import read_reference, source_version
from app.services.workspace.tools import execute_workspace_tool
from app.services.workspace.ingest import UploadInput, ingest
from app.services.workspace.containers import WorkspaceContainer
from app.services.workspaces import list_workspaces as list_core_workspaces, require_workspace_customer, resolve_workspace

router = APIRouter(prefix="/voice-workspaces", tags=["voice-workspaces"])


async def _commit_and_schedule(session: AsyncSession, result: dict) -> None:
    await session.commit()
    if result.get("status") == "queued" and result.get("job_id"):
        jobs_service.enqueue_job(result["job_id"])


@router.get("")
async def list_workspaces(*, workspace_id: str | None = Query(default=None), customer_id: int | None = Query(default=None),
                          session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> list[dict]:
    customer = await require_workspace_customer(session, user, customer_id)
    if workspace_id is not None:
        parent = await resolve_workspace(session, customer_id=customer, user_id=user.id, workspace_id=workspace_id)
        parent_ids = [parent.id]
    else:
        parent_ids = [row.id for row in await list_core_workspaces(session, customer_id=customer, user_id=user.id)]
    rows = list((await session.execute(select(VoiceWorkspace).where(VoiceWorkspace.owner_user_id == user.id,
        VoiceWorkspace.customer_id == customer, VoiceWorkspace.workspace_id.in_(parent_ids))
        .order_by(VoiceWorkspace.updated_at.desc()).limit(100))).scalars())
    result = []
    for row in rows:
        await require_workspace(session, row.id, user)
        result.append({"id": row.id, "workspace_id": row.workspace_id, "chat_id": row.chat_id,
                       "customer_id": row.customer_id, "title": row.title, "module": row.module,
                       "revision": row.revision, "state": row.state})
    await session.commit()
    return result


@router.post("", status_code=201)
async def post_workspace(body: WorkspaceCreate, *, customer_id: int | None = Query(default=None),
                         session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    container = WorkspaceContainer(body.workspace_id, body.chat_id, customer_id)
    workspace = await create_workspace(session, user, title=body.title, module=body.module,
                                       idempotency_key=body.idempotency_key, language=body.language, container=container)
    result = await workspace_out(session, workspace)
    await session.commit()
    return result


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    result = await workspace_out(session, await require_workspace(session, workspace_id, user))
    await session.commit()
    return result


@router.patch("/{workspace_id}")
async def update_workspace(workspace_id: str, body: WorkspacePatch, *, session: AsyncSession = Depends(get_session), user: UserAccount = Depends(get_current_user)) -> dict:
    if has_pending_writes(session):
        raise RuntimeError("Workspace changes require a clean transaction")
    workspace = await require_workspace(session, workspace_id, user)
    arguments = body.model_dump(exclude={"idempotency_key", "expected_revision"})
    existing = await session.scalar(select(WorkspaceOperation.id).where(
        WorkspaceOperation.workspace_id == workspace_id, WorkspaceOperation.idempotency_key == body.idempotency_key))
    if existing is None:
        if workspace.revision != body.expected_revision:
            raise HTTPException(status_code=409, detail="workspace_revision_conflict")
        from app.services.workspace.selection_verification import prepare_pdf_selection
        workspace = await prepare_pdf_selection(session, workspace, user, body.state)
    operation, accepted = await accept_operation(session, workspace, tool_name="update_workspace", arguments=arguments,
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


@router.get("/{workspace_id}/sources/{source_id}")
async def get_workspace_source(workspace_id: str, source_id: str, *, session: AsyncSession = Depends(get_session),
                               user: UserAccount = Depends(get_current_user)) -> dict:
    from app.services.stored_objects import serialize_underlag
    from app.services.workspace.service import require_source
    workspace = await require_workspace(session, workspace_id, user)
    source = await require_source(session, workspace, source_id)
    return {**serialize_underlag(source, include_text=True), "source_version": source_version(source)}


@router.get("/{workspace_id}/sources/{source_id}/file")
async def get_workspace_source_file(workspace_id: str, source_id: str, *, session: AsyncSession = Depends(get_session),
                                    user: UserAccount = Depends(get_current_user)):
    from hashlib import sha256
    from urllib.parse import quote
    from fastapi import Response
    from app.services.object_storage import get_object
    from app.services.workspace.service import require_source
    workspace = await require_workspace(session, workspace_id, user)
    source = await require_source(session, workspace, source_id)
    bucket, key, filename, mime = source.bucket, source.object_key, source.filename, source.content_type
    owner_id, version = user.id, source_version(source)
    await session.rollback()
    data, _stored_mime = await get_object(bucket, key)
    owner = await session.get(UserAccount, owner_id, populate_existing=True)
    if owner is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    workspace = await require_workspace(session, workspace_id, owner)
    source = await require_source(session, workspace, source_id)
    if (source_version(source) != version
            or (source.bucket, source.object_key, source.filename, source.content_type) != (bucket, key, filename, mime)):
        raise HTTPException(status_code=409, detail="workspace_source_changed_during_read")
    await session.rollback()
    return Response(data, media_type=mime,
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
                             "X-Workspace-Source-Version": version,
                             "X-Workspace-File-Sha256": sha256(data).hexdigest()})


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
