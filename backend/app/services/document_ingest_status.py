"""Reconcile interrupted document metadata in the startup job transaction."""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, StoredObject
from app.services.document_knowledge import DOCUMENT_INGEST_JOB_KIND
from app.services.object_storage import KIND_UNDERLAG


async def reconcile_failed_document_ingest(session: AsyncSession, *, message: str) -> None:
    current_job = select(Job.id).where(
        Job.id == StoredObject.knowledge_job_id,
        Job.customer_id == StoredObject.customer_id,
        Job.kind == DOCUMENT_INGEST_JOB_KIND,
        Job.status.in_(("failed", "cancelled")),
        Job.request["object_id"].as_string() == StoredObject.id,
        Job.request["owner_user_id"].as_string() == StoredObject.owner_user_id,
    )
    error = current_job.with_only_columns(Job.error).scalar_subquery()
    await session.execute(
        update(StoredObject)
        .where(
            StoredObject.kind == KIND_UNDERLAG,
            StoredObject.knowledge_status.in_(("pending", "running")),
            current_job.exists(),
        )
        .values(knowledge_status="failed", knowledge_error=func.coalesce(error, message))
        .execution_options(synchronize_session=False)
    )
