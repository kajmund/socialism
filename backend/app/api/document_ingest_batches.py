"""Voice-workspace batch ingest. Each file is one existing document_ingest job."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.database.session import get_session
from app.services import jobs as jobs_service
from app.services.document_ingest_batch.service import (
    BatchUpload,
    add_file,
    create_batch,
    list_batches,
    load_batch,
    retry_item,
)
from app.services.object_storage import MAX_UNDERLAG_BYTES
from app.services.workspace.service import require_workspace

router = APIRouter(prefix="/voice-workspaces", tags=["voice-workspaces"])


@router.post("/{workspace_id}/ingest-batches", status_code=201)
async def post_ingest_batch(
    workspace_id: str,
    *,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    result = await create_batch(session, workspace, user)
    await session.commit()
    return result


@router.get("/{workspace_id}/ingest-batches")
async def get_ingest_batches(
    workspace_id: str,
    *,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[dict]:
    workspace = await require_workspace(session, workspace_id, user)
    result = await list_batches(session, workspace)
    await session.commit()
    return result


@router.get("/{workspace_id}/ingest-batches/{batch_id}")
async def get_ingest_batch(
    workspace_id: str,
    batch_id: str,
    *,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    result = await load_batch(session, workspace, batch_id)
    await session.commit()
    return result


@router.post("/{workspace_id}/ingest-batches/{batch_id}/files", status_code=201)
async def post_ingest_batch_file(
    workspace_id: str,
    batch_id: str,
    *,
    idempotency_key: str = Form(...),
    client_key: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    raw = await file.read(MAX_UNDERLAG_BYTES + 1)
    result = await add_file(session, workspace, user, BatchUpload(
        batch_id=batch_id,
        client_key=client_key,
        filename=file.filename or "file",
        content_type=file.content_type or "application/octet-stream",
        data=raw,
        idempotency_key=idempotency_key,
    ))
    await _commit_and_schedule(session, result)
    return result


@router.post("/{workspace_id}/ingest-batches/{batch_id}/items/{item_id}/retry")
async def post_ingest_batch_retry(
    workspace_id: str,
    batch_id: str,
    item_id: str,
    *,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict:
    workspace = await require_workspace(session, workspace_id, user)
    result = await retry_item(session, workspace, batch_id=batch_id, item_id=item_id)
    await _commit_and_schedule(session, result)
    return result


def _job_ids(payload: dict) -> list[str]:
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    seen: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("stage") != "extracting":
            continue
        job_id = str(item.get("job_id") or "")
        if job_id and job_id not in seen:
            seen.append(job_id)
    return seen


async def _commit_and_schedule(session: AsyncSession, payload: dict) -> None:
    await session.commit()
    for job_id in _job_ids(payload):
        jobs_service.enqueue_job(job_id)
