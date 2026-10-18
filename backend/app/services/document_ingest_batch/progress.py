"""Write measured batch-item progress. Never opens OverGraph."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.document_ingest_batches import DocumentIngestBatch, DocumentIngestBatchItem
from app.database.graph_v2 import GraphIngestWork
from app.database.models import Job
from app.serializers import utcnow
from app.services.document_ingest_batch.stages import (
    COMPLETED,
    EXTRACTING,
    FAILED,
    FAILED_KNOWLEDGE,
    INDEXING,
    PROCESSING,
    READY,
    TERMINAL_STATUSES,
    UPLOADING,
    ingest_percent,
    upload_percent,
)

_ABANDONED_UPLOAD = timedelta(minutes=2)
_ABANDONED_UPLOAD_ERROR = "upload_abandoned"


async def record_extracting(factory: async_sessionmaker[AsyncSession], job_id: str) -> None:
    async with factory() as session:
        await _patch(
            session, job_ids=[job_id],
            stage=EXTRACTING, status=PROCESSING, ingest_progress=0, searchable=False,
        )
        await session.commit()


async def record_indexing(
    factory: async_sessionmaker[AsyncSession],
    job_id: str,
    *,
    object_id: str,
    document_version_id: str | None,
    unit_total: int,
) -> None:
    async with factory() as session:
        await _patch(
            session, job_ids=[job_id],
            stage=INDEXING, status=PROCESSING, searchable=False, error=None,
            document_id=object_id, document_version_id=document_version_id,
            unit_total=unit_total, ingest_progress=0,
        )
        await session.commit()


async def record_job_result(
    factory: async_sessionmaker[AsyncSession],
    job_id: str,
    result: dict[str, object],
) -> None:
    async with factory() as session:
        await _patch(session, job_ids=[job_id], **_fields_from_job_result(result))
        await session.commit()


async def record_job_failed(factory: async_sessionmaker[AsyncSession], job_id: str, message: str) -> None:
    async with factory() as session:
        await _patch(session, job_ids=[job_id], stage=FAILED, status=FAILED, error=message[:2000])
        await session.commit()


async def record_searchable(
    factory: async_sessionmaker[AsyncSession],
    *,
    graph_work_id: str,
    document_id: str,
    document_version_id: str,
    unit_total: int,
) -> None:
    async with factory() as session:
        await _patch(
            session, graph_work_ids=[graph_work_id],
            stage=READY, status=READY, searchable=True,
            document_id=document_id, document_version_id=document_version_id,
            unit_total=unit_total, unit_done=unit_total,
            ingest_progress=100, upload_progress=100,
        )
        await _refresh_batches(session, graph_work_ids=[graph_work_id])
        await session.commit()


async def reconcile_abandoned_uploads(session: AsyncSession, items: Sequence[DocumentIngestBatchItem]) -> None:
    cutoff = utcnow() - _ABANDONED_UPLOAD
    for item in items:
        if item.stage != UPLOADING or item.stored_object_id or item.job_id:
            continue
        if item.status in TERMINAL_STATUSES:
            continue
        updated = item.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=cutoff.tzinfo)
        if updated > cutoff:
            continue
        item.stage = FAILED
        item.status = FAILED
        item.searchable = False
        item.error = _ABANDONED_UPLOAD_ERROR


async def reconcile_jobs(session: AsyncSession, items: Sequence[DocumentIngestBatchItem]) -> None:
    pending = [item for item in items if item.job_id and item.status not in TERMINAL_STATUSES]
    if not pending:
        return
    rows = {
        row.id: row
        for row in (
            await session.scalars(select(Job).where(Job.id.in_([item.job_id for item in pending])))
        ).all()
    }
    for item in pending:
        job = rows.get(item.job_id or "")
        if job is None:
            continue
        if job.status in {"failed", "cancelled"}:
            item.stage = FAILED
            item.status = FAILED
            item.searchable = False
            item.error = (job.error or "document ingest failed")[:2000]
            continue
        if job.status == "succeeded" and item.stage == EXTRACTING:
            _apply_fields(item, _fields_from_job_result(dict(job.result or {})))


async def reconcile_graph_work(session: AsyncSession, items: Sequence[DocumentIngestBatchItem]) -> None:
    pending = [item for item in items if item.graph_work_id and item.status not in TERMINAL_STATUSES]
    if not pending:
        return
    rows = {
        row.id: row
        for row in (
            await session.scalars(
                select(GraphIngestWork).where(
                    GraphIngestWork.id.in_([item.graph_work_id for item in pending]),
                )
            )
        ).all()
    }
    for item in pending:
        work = rows.get(item.graph_work_id or "")
        if work is None:
            continue
        if work.status == "completed":
            item.stage = READY
            item.status = READY
            item.searchable = True
            item.unit_done = item.unit_total
            item.ingest_progress = 100
            item.upload_progress = upload_percent(stored=item.stored_object_id is not None)
            item.error = None
        elif work.status == "failed":
            item.stage = FAILED
            item.status = FAILED
            item.searchable = False
            item.ingest_progress = ingest_percent(
                unit_done=item.unit_done, unit_total=item.unit_total, searchable=False,
            )
            item.error = (work.last_error or "document catalog write failed")[:2000]


def _fields_from_job_result(result: dict[str, object]) -> dict[str, object]:
    status = str(result.get("status") or "")
    version_id = str(result.get("document_version_id") or "") or None
    work_id = str(result.get("graph_work_id") or "") or None
    units = int(result.get("chunks_indexed") or 0)
    if status in FAILED_KNOWLEDGE:
        return {
            "stage": FAILED, "status": FAILED, "searchable": False,
            "error": str(result.get("message") or status)[:2000],
            "document_version_id": version_id, "graph_work_id": work_id, "unit_total": units,
        }
    return {
        "stage": INDEXING, "status": PROCESSING, "searchable": False, "error": None,
        "document_id": str(result.get("object_id") or "") or None,
        "document_version_id": version_id, "graph_work_id": work_id,
        "unit_total": units, "ingest_progress": 0,
    }


def _apply_fields(item: DocumentIngestBatchItem, fields: dict[str, object]) -> None:
    for key, value in fields.items():
        if value is not None or key == "error":
            setattr(item, key, value)


async def _patch(session: AsyncSession, **values: object) -> None:
    job_ids = list(values.pop("job_ids", []) or [])
    graph_work_ids = list(values.pop("graph_work_ids", []) or [])
    payload = {key: value for key, value in values.items() if value is not None or key == "error"}
    payload["updated_at"] = utcnow()
    stmt = update(DocumentIngestBatchItem)
    if job_ids:
        stmt = stmt.where(DocumentIngestBatchItem.job_id.in_(job_ids))
    elif graph_work_ids:
        stmt = stmt.where(DocumentIngestBatchItem.graph_work_id.in_(graph_work_ids))
    else:
        return
    await session.execute(stmt.values(**payload))


async def _refresh_batches(session: AsyncSession, *, graph_work_ids: Sequence[str]) -> None:
    batch_ids = list(await session.scalars(
        select(DocumentIngestBatchItem.batch_id).where(
            DocumentIngestBatchItem.graph_work_id.in_(list(graph_work_ids)),
        ).distinct()
    ))
    for batch_id in batch_ids:
        items = list(await session.scalars(
            select(DocumentIngestBatchItem).where(DocumentIngestBatchItem.batch_id == batch_id)
        ))
        if items and all(item.status in TERMINAL_STATUSES for item in items):
            batch = await session.get(DocumentIngestBatch, batch_id)
            if batch is not None:
                batch.status = COMPLETED
                batch.updated_at = utcnow()
