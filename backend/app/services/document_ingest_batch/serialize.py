"""Batch API payload. Progress is stored numbers, not inferred bars."""

from app.database.document_ingest_batches import DocumentIngestBatch, DocumentIngestBatchItem
from app.schemas.domain import format_date
from app.services.document_ingest_batch.stages import ingest_percent, upload_percent


def item_out(item: DocumentIngestBatchItem) -> dict[str, object]:
    stored = item.stored_object_id is not None
    upload = 100 if item.upload_progress >= 100 and stored else upload_percent(stored=stored)
    ingest = ingest_percent(
        unit_done=item.unit_done, unit_total=item.unit_total, searchable=item.searchable,
    )
    if item.searchable:
        ingest = 100
    elif item.ingest_progress and not item.searchable:
        ingest = min(item.ingest_progress, 99)
    return {
        "id": item.id,
        "client_key": item.client_key,
        "filename": item.filename,
        "content_type": item.content_type,
        "size_bytes": item.size_bytes,
        "upload_progress": upload,
        "ingest_progress": ingest,
        "stage": item.stage,
        "status": item.status,
        "searchable": item.searchable,
        "stored_object_id": item.stored_object_id,
        "document_id": item.document_id,
        "document_version_id": item.document_version_id,
        "job_id": item.job_id,
        "error": item.error,
        "created_at": format_date(item.created_at),
    }


def batch_out(batch: DocumentIngestBatch, items: list[DocumentIngestBatchItem]) -> dict[str, object]:
    return {
        "id": batch.id,
        "voice_workspace_id": batch.voice_workspace_id,
        "status": batch.status,
        "created_at": format_date(batch.created_at),
        "items": [item_out(item) for item in items],
    }
