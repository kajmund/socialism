"""Workspace upload identity is SHA-256 of the file bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.document_ingest_batches import DocumentIngestBatch, DocumentIngestBatchItem
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, StoredObject
from app.database.workspace_models import VoiceWorkspace, WorkspaceSource
from app.services.document_ingest_batch.stages import FAILED, SKIPPED
from app.services.document_ingest_status import document_text_ready


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ContentDuplicate:
    source: StoredObject | None


async def workspace_content_duplicate(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    digest: str,
    *,
    except_item_id: str | None = None,
) -> ContentDuplicate | None:
    source = await existing_workspace_source(session, workspace, digest)
    if source is not None:
        return ContentDuplicate(source)
    if except_item_id is None:
        return None
    rival = await _earlier_batch_claim(session, workspace, digest, except_item_id)
    if rival is None:
        return None
    if rival.stored_object_id is None:
        return ContentDuplicate(None)
    found = await session.get(StoredObject, rival.stored_object_id)
    return ContentDuplicate(found)


async def existing_workspace_source(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    digest: str,
) -> StoredObject | None:
    by_hash = await session.scalar(
        select(StoredObject)
        .join(WorkspaceSource, WorkspaceSource.source_id == StoredObject.id)
        .where(
            WorkspaceSource.workspace_id == workspace.id,
            StoredObject.customer_id == workspace.customer_id,
            StoredObject.content_sha256 == digest,
        )
        .order_by(StoredObject.created_at.asc(), StoredObject.id.asc())
    )
    if by_hash is not None:
        return by_hash
    return await session.scalar(
        select(StoredObject)
        .join(WorkspaceSource, WorkspaceSource.source_id == StoredObject.id)
        .join(CanonicalDocumentRecord, CanonicalDocumentRecord.source_object_id == StoredObject.id)
        .join(DocumentVersionRecord, DocumentVersionRecord.document_id == CanonicalDocumentRecord.id)
        .where(
            WorkspaceSource.workspace_id == workspace.id,
            StoredObject.customer_id == workspace.customer_id,
            DocumentVersionRecord.content_hash == digest,
            DocumentVersionRecord.superseded_at.is_(None),
        )
        .order_by(StoredObject.created_at.asc(), StoredObject.id.asc())
    )


def skipped_source_fields(source: StoredObject | None) -> dict[str, object]:
    ready = source is not None and (
        source.knowledge_status == "ready" or document_text_ready(source)
    )
    return {
        "stored_object_id": source.id if source is not None else None,
        "document_id": source.id if source is not None else None,
        "searchable": ready,
        "upload_progress": 100 if source is not None else 0,
        "ingest_progress": 100 if ready else 0,
    }


async def _earlier_batch_claim(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    digest: str,
    except_item_id: str,
) -> DocumentIngestBatchItem | None:
    item = await session.get(DocumentIngestBatchItem, except_item_id)
    if item is None:
        return None
    rivals = list(await session.scalars(
        select(DocumentIngestBatchItem)
        .join(DocumentIngestBatch)
        .where(
            DocumentIngestBatch.voice_workspace_id == workspace.id,
            DocumentIngestBatchItem.content_sha256 == digest,
            DocumentIngestBatchItem.id != except_item_id,
            or_(
                DocumentIngestBatchItem.stored_object_id.is_not(None),
                DocumentIngestBatchItem.stage.notin_((FAILED, SKIPPED)),
            ),
        )
    ))
    earlier = [
        row for row in rivals
        if (row.created_at, row.id) < (item.created_at, item.id)
    ]
    earlier.sort(key=lambda row: (row.created_at, row.id))
    return earlier[0] if earlier else None
