"""Job serialization and realtime events shared by domain job adapters."""

from datetime import UTC, datetime

from app.database.models import Job
from app.realtime.hub import job_hub
from app.schemas.domain import JobOut


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def serialize_job(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        customer_id=job.customer_id,
        kind=job.kind,
        status=job.status,  # type: ignore[arg-type]
        label=job.label,
        request=dict(job.request or {}),
        result=dict(job.result) if job.result else None,
        error=job.error,
        created_at=_dt(job.created_at) or "",
        started_at=_dt(job.started_at),
        finished_at=_dt(job.finished_at),
        archived_at=_dt(job.archived_at),
        updated_at=_dt(job.updated_at) or "",
    )


async def publish_job(job: Job) -> None:
    """Push a job.updated event to connected WebSocket clients."""
    await job_hub.publish(
        {"type": "job.updated", "job": serialize_job(job).model_dump(mode="json")}
    )
