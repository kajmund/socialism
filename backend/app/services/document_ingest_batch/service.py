"""Create and bind batch ingest items. Upload still uses workspace ingest."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.document_ingest_batches import DocumentIngestBatch, DocumentIngestBatchItem
from app.database.models import StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace
from app.serializers import utcnow
from app.services.document_ingest_batch.progress import (
    reconcile_abandoned_uploads,
    reconcile_graph_work,
    reconcile_jobs,
)
from app.services.document_ingest_batch.serialize import batch_out
from app.services.document_ingest_batch.stages import (
    COMPLETED,
    EXTRACTING,
    FAILED,
    PROCESSING,
    SKIPPED,
    TERMINAL_STATUSES,
    UPLOADING,
    WAITING,
)
from app.services.workspace.ingest import UploadInput, ingest
from app.services.workspace.service import accept_operation, fingerprint, new_id, require_workspace
from app.services.workspace.source_content import file_sha256, skipped_source_fields, workspace_content_duplicate
from app.services.workspace.source_ingest_retry import retry_failed_source


@dataclass(frozen=True)
class BatchUpload:
    batch_id: str
    client_key: str
    filename: str
    content_type: str
    data: bytes
    idempotency_key: str


async def create_batch(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount) -> dict[str, object]:
    batch = DocumentIngestBatch(
        id=new_id(),
        customer_id=workspace.customer_id,
        voice_workspace_id=workspace.id,
        owner_user_id=user.id,
        status=PROCESSING,
    )
    session.add(batch)
    await session.flush()
    return batch_out(batch, [])


async def list_batches(
    session: AsyncSession, workspace: VoiceWorkspace, *, limit: int = 20,
) -> list[dict[str, object]]:
    rows = list(await session.scalars(
        select(DocumentIngestBatch).where(
            DocumentIngestBatch.voice_workspace_id == workspace.id,
            DocumentIngestBatch.customer_id == workspace.customer_id,
        ).order_by(DocumentIngestBatch.created_at.desc()).limit(limit)
    ))
    return [await load_batch(session, workspace, batch.id) for batch in rows]


async def load_batch(session: AsyncSession, workspace: VoiceWorkspace, batch_id: str) -> dict[str, object]:
    batch, items = await _owned_batch(session, workspace, batch_id)
    await reconcile_jobs(session, items)
    await reconcile_graph_work(session, items)
    await reconcile_abandoned_uploads(session, items)
    if items and all(item.status in TERMINAL_STATUSES for item in items):
        batch.status = COMPLETED
        batch.updated_at = utcnow()
    elif items:
        batch.status = PROCESSING
        batch.updated_at = utcnow()
    return batch_out(batch, items)


async def add_file(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    user: UserAccount,
    upload: BatchUpload,
) -> dict[str, object]:
    batch, _items = await _owned_batch(session, workspace, upload.batch_id)
    item = await _item_for_key(
        session,
        batch_id=batch.id,
        client_key=upload.client_key,
        filename=upload.filename,
        content_type=upload.content_type,
        size_bytes=len(upload.data),
    )
    item.stage = UPLOADING
    item.status = PROCESSING
    item.content_sha256 = file_sha256(upload.data)
    await session.flush()
    item_id = item.id
    digest = item.content_sha256
    workspace_id = workspace.id
    user_id = user.id
    batch_id = upload.batch_id
    duplicate = await workspace_content_duplicate(
        session, workspace, digest, except_item_id=item_id,
    )
    if duplicate is not None:
        await _skip_item(session, item_id, duplicate.source)
        user = await session.get(UserAccount, user_id)
        workspace = await require_workspace(session, workspace_id, user)
        return await load_batch(session, workspace, batch_id)
    try:
        operation, accepted = await accept_operation(
            session, workspace, tool_name="upload_source", idempotency_key=upload.idempotency_key,
            arguments={
                "filename": upload.filename,
                "content_type": upload.content_type,
                "content_hash": fingerprint(upload.data.hex()),
            },
        )
        if accepted:
            await ingest(
                session, workspace, operation,
                upload=UploadInput(
                    upload.data,
                    upload.filename or "file",
                    upload.content_type or "application/octet-stream",
                ),
            )
        result = dict(operation.result or {})
        if result.get("status") == "skipped" and result.get("source_id"):
            source = await session.get(StoredObject, str(result["source_id"]))
            await _skip_item(session, item_id, source)
        elif result.get("status") == "queued" and result.get("source_id") and result.get("job_id"):
            bound = await session.get(DocumentIngestBatchItem, item_id)
            _bind_upload(bound, result)
        else:
            await _fail_item(
                session, item_id, str(result.get("error") or result.get("detail") or "upload_failed"),
            )
    except HTTPException as exc:
        await _fail_item(session, item_id, str(exc.detail))
    except RuntimeError as exc:
        await _fail_item(session, item_id, str(exc))
    user = await session.get(UserAccount, user_id)
    workspace = await require_workspace(session, workspace_id, user)
    return await load_batch(session, workspace, batch_id)


async def _skip_item(session: AsyncSession, item_id: str, source: StoredObject | None) -> None:
    item = await session.get(DocumentIngestBatchItem, item_id)
    if item is None:
        return
    item.stage = SKIPPED
    item.status = SKIPPED
    item.error = None
    item.job_id = None
    item.updated_at = utcnow()
    for key, value in skipped_source_fields(source).items():
        setattr(item, key, value)


async def _fail_item(session: AsyncSession, item_id: str, error: str) -> None:
    item = await session.get(DocumentIngestBatchItem, item_id)
    if item is None:
        return
    item.stage = FAILED
    item.status = FAILED
    item.error = error[:2000]
    item.updated_at = utcnow()


async def retry_item(
    session: AsyncSession, workspace: VoiceWorkspace, *, batch_id: str, item_id: str,
) -> dict[str, object]:
    _batch, items = await _owned_batch(session, workspace, batch_id)
    item = next((row for row in items if row.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="document_ingest_item_not_found")
    if item.status != FAILED or not item.stored_object_id:
        raise HTTPException(status_code=409, detail="document_ingest_retry_requires_failed_upload")
    source = await session.get(StoredObject, item.stored_object_id)
    if source is None:
        raise HTTPException(status_code=404, detail="document_ingest_source_not_found")
    result = await retry_failed_source(session, workspace, source)
    if result.get("status") == "queued":
        item.job_id = str(result.get("job_id") or "") or item.job_id
        item.stage = EXTRACTING
        item.status = PROCESSING
        item.searchable = False
        item.ingest_progress = 0
        item.unit_done = 0
        item.error = None
        item.updated_at = utcnow()
    return await load_batch(session, workspace, batch_id)


async def _owned_batch(
    session: AsyncSession, workspace: VoiceWorkspace, batch_id: str,
) -> tuple[DocumentIngestBatch, list[DocumentIngestBatchItem]]:
    batch = await session.get(DocumentIngestBatch, batch_id)
    if (
        batch is None
        or batch.voice_workspace_id != workspace.id
        or batch.customer_id != workspace.customer_id
    ):
        raise HTTPException(status_code=404, detail="document_ingest_batch_not_found")
    items = list(await session.scalars(
        select(DocumentIngestBatchItem).where(
            DocumentIngestBatchItem.batch_id == batch.id,
        ).order_by(DocumentIngestBatchItem.created_at, DocumentIngestBatchItem.id)
    ))
    return batch, items


async def _item_for_key(
    session: AsyncSession,
    *,
    batch_id: str,
    client_key: str,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> DocumentIngestBatchItem:
    item = await session.scalar(
        select(DocumentIngestBatchItem).where(
            DocumentIngestBatchItem.batch_id == batch_id,
            DocumentIngestBatchItem.client_key == client_key,
        )
    )
    if item is not None:
        item.filename = filename[:255]
        item.content_type = content_type[:128]
        item.size_bytes = size_bytes
        item.updated_at = utcnow()
        return item
    item = DocumentIngestBatchItem(
        id=new_id(),
        batch_id=batch_id,
        client_key=client_key[:64],
        filename=filename[:255],
        content_type=content_type[:128],
        size_bytes=size_bytes,
        stage=WAITING,
        status="pending",
    )
    session.add(item)
    return item


def _bind_upload(item: DocumentIngestBatchItem, result: dict[str, object]) -> None:
    item.stored_object_id = str(result["source_id"])
    item.job_id = str(result["job_id"])
    item.upload_progress = 100
    item.stage = EXTRACTING
    item.status = PROCESSING
    item.searchable = False
    item.error = None
    item.updated_at = utcnow()
