"""Workspace-owned three-phase upload and URL import transactions."""

import secrets
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, Kund, StoredObject
from app.database.workspace_models import Workspace, WorkspaceOperation
from app.serializers import utcnow
from app.services.document_knowledge import DOCUMENT_INGEST_JOB_KIND
from app.services.object_storage import (
    KIND_UNDERLAG, UNDERLAG_DOCX_TYPE, bucket_name, ensure_bucket, module_prefix,
    put_object, safe_filename, validate_underlag,
)
from app.services.underlag_pdf import convert_docx_to_pdf_async
from app.services.workspace.service import add_source
from app.services.workspace.url_ingest import SourceImportError, fetch_source_url


@dataclass(frozen=True)
class StorageTarget:
    bucket: str
    owner_user_id: str
    module: str


@dataclass(frozen=True)
class UploadInput:
    data: bytes
    filename: str
    content_type: str


async def _store(target: StorageTarget, value: UploadInput) -> dict:
    content_type = validate_underlag(value.filename, value.content_type, value.data)
    name, data = safe_filename(value.filename), value.data
    if content_type == UNDERLAG_DOCX_TYPE:
        data = await convert_docx_to_pdf_async(data, filename=name)
        content_type, name = "application/pdf", f"{Path(name).stem}.pdf"
    object_id = secrets.token_hex(16)
    key = f"{module_prefix(target.module)}/underlag/{target.owner_user_id}/{object_id}/{name}"
    await ensure_bucket(target.bucket)
    await put_object(target.bucket, key, data, content_type)
    return {"id": object_id, "bucket": target.bucket, "object_key": key, "filename": name,
            "content_type": content_type, "size_bytes": len(data)}


async def _persist(session: AsyncSession, workspace: Workspace, stored: dict, *, source_url: str | None = None) -> dict:
    await session.refresh(workspace)
    source = StoredObject(**stored, customer_id=workspace.customer_id, owner_user_id=workspace.owner_user_id,
        module=workspace.module, kind=KIND_UNDERLAG, extraction_status="pending", knowledge_status="pending", created_at=utcnow())
    session.add(source)
    await session.flush()
    job = Job(id=f"job_{secrets.token_hex(8)}", customer_id=workspace.customer_id,
        kind=DOCUMENT_INGEST_JOB_KIND, status="pending", label=source.filename,
        request={"workspace_id": workspace.id, "object_id": source.id, "owner_user_id": workspace.owner_user_id},
        created_at=utcnow(), updated_at=utcnow())
    session.add(job)
    await session.flush()
    source.knowledge_job_id = job.id
    await add_source(session, workspace, source.id, source_url=source_url)
    return {"status": "queued", "source_id": source.id, "job_id": job.id, "ingest_status": source.knowledge_status}


async def ingest(session: AsyncSession, workspace: Workspace, operation: WorkspaceOperation,
                 *, upload: UploadInput | None = None, url: str | None = None) -> dict:
    customer = await session.get(Kund, workspace.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="workspace_customer_not_found")
    target = StorageTarget(bucket_name(customer.slug), workspace.owner_user_id, workspace.module)
    operation_id = operation.id
    operation.status = "running"
    # The request's command transaction owns only this accepted operation.
    await session.commit()
    operation.external_started = True
    stored = None
    try:
        final_url = None
        if url:
            raw, mime, name, final_url = await fetch_source_url(url)
            upload = UploadInput(raw, name, mime)
        if upload is None:
            raise ValueError("source_upload_required")
        stored = await _store(target, upload)
    except (ValueError, SourceImportError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="source_url_fetch_failed") from exc
    finally:
        if stored is None:
            await session.rollback()
            failed = await session.get(WorkspaceOperation, operation_id)
            failed.status = "failed"
            failed.result = {"operation_id": operation_id, "status": "failed", "error": "workspace_source_import_failed"}
            await session.commit()
            operation.external_started = False
    result = await _persist(session, workspace, stored, source_url=final_url)
    operation = await session.get(WorkspaceOperation, operation_id)
    operation.result = {**result, "operation_id": operation.id, **({"source_url": final_url} if final_url else {})}
    operation.status, operation.job_id = "queued", result["job_id"]
    return operation.result


async def ingest_url(session: AsyncSession, workspace: Workspace, operation: WorkspaceOperation, *, url: str) -> dict:
    return await ingest(session, workspace, operation, url=url)
