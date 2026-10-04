"""Explicit retries replace a failed source's current job in the command transaction."""

import secrets

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, StoredObject
from app.database.workspace_models import VoiceWorkspace
from app.serializers import utcnow
from app.services.document_knowledge import DOCUMENT_INGEST_JOB_KIND
from app.services.workspace.service import require_source


def _source_result(source: StoredObject, *, status: str = "completed") -> dict[str, object]:
    return {"status": status, "source_id": source.id, "job_id": source.knowledge_job_id,
            "ingest_status": source.knowledge_status}


def _matching_job(job: Job | None, source: StoredObject) -> bool:
    request = job.request if job is not None and isinstance(job.request, dict) else {}
    return (job is not None and job.kind == DOCUMENT_INGEST_JOB_KIND
            and source.owner_user_id is not None and source.workspace_id is not None
            and job.customer_id == source.customer_id
            and request.get("object_id") == source.id
            and request.get("owner_user_id") == source.owner_user_id
            and request.get("workspace_id") == source.workspace_id)


async def retry_failed_source(
    session: AsyncSession, workspace: VoiceWorkspace, source: StoredObject,
) -> dict[str, object]:
    if source.knowledge_status != "failed":
        return _source_result(source)
    previous = await session.get(Job, source.knowledge_job_id) if source.knowledge_job_id else None
    if not _matching_job(previous, source) or source.customer_id != workspace.customer_id:
        raise HTTPException(status_code=404, detail="workspace_job_not_found")
    if previous.status != "failed":
        return _source_result(source)
    now = utcnow()
    replacement = Job(id=f"job_{secrets.token_hex(8)}", customer_id=source.customer_id,
        kind=DOCUMENT_INGEST_JOB_KIND, status="pending", label=f"Dokumentförståelse: {source.filename[:80]}",
        request={"object_id": source.id, "owner_user_id": source.owner_user_id, "workspace_id": source.workspace_id},
        created_at=now, updated_at=now)
    session.add(replacement)
    await session.flush()
    current_failed_job = select(Job.id).where(
        Job.id == StoredObject.knowledge_job_id, Job.status == "failed",
        Job.kind == DOCUMENT_INGEST_JOB_KIND, Job.customer_id == StoredObject.customer_id,
        Job.request["object_id"].as_string() == StoredObject.id,
        Job.request["owner_user_id"].as_string() == StoredObject.owner_user_id,
        Job.request["workspace_id"].as_string() == StoredObject.workspace_id,
    )
    claimed = await session.scalar(update(StoredObject).where(
        StoredObject.id == source.id, StoredObject.customer_id == workspace.customer_id,
        StoredObject.owner_user_id == source.owner_user_id, StoredObject.workspace_id == source.workspace_id,
        StoredObject.knowledge_job_id == previous.id, StoredObject.knowledge_status == "failed",
        current_failed_job.exists(),
    ).values(knowledge_job_id=replacement.id, knowledge_status="pending", knowledge_error=None)
      .returning(StoredObject.id).execution_options(synchronize_session=False))
    if claimed is None:
        await session.delete(replacement)
        await session.flush()
        source = await require_source(session, workspace, source.id, member=False)
    else:
        await session.refresh(source)
    return _source_result(source, status="queued" if claimed is not None else "completed")
