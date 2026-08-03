"""Background job create / run / query."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Job
from app.database.session import SessionLocal
from app.schemas.domain import (
    JobCreate,
    JobOut,
    JobStatus,
    PopulationGenerateJobRequest,
    PopulationGenerateRequest,
)
from app.serializers import utcnow
from app.services import population_generate as gen
from app.services.population_persist import (
    create_population_from_generation,
    update_population_from_generation,
)

logger = logging.getLogger(__name__)

_session_factory: async_sessionmaker[AsyncSession] | None = None


def set_job_session_factory(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Tests inject an in-memory session factory; production uses SessionLocal."""
    global _session_factory
    _session_factory = factory


def job_session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory or SessionLocal


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def serialize_job(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,  # type: ignore[arg-type]
        label=job.label,
        request=dict(job.request or {}),
        result=dict(job.result) if job.result else None,
        error=job.error,
        created_at=_dt(job.created_at) or "",
        started_at=_dt(job.started_at),
        finished_at=_dt(job.finished_at),
        updated_at=_dt(job.updated_at) or "",
    )


async def create_job(session: AsyncSession, body: JobCreate) -> Job:
    if body.kind == "population_generate":
        # Validate shape early so the API fails before the worker starts.
        PopulationGenerateJobRequest.model_validate(body.request)
    else:
        raise ValueError(f"Unsupported job kind: {body.kind}")

    label = (body.label or "").strip() or str(body.request.get("name") or "Jobb")
    job = Job(
        id=f"job_{secrets.token_hex(8)}",
        kind=body.kind,
        status="pending",
        label=label,
        request=body.request,
        result=None,
        error=None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def schedule_job(job_id: str) -> None:
    asyncio.create_task(_run_job(job_id), name=f"job:{job_id}")


async def _run_job(job_id: str) -> None:
    factory = job_session_factory()
    try:
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            if job.status not in {"pending", "running"}:
                return
            job.status = "running"
            job.started_at = utcnow()
            job.updated_at = utcnow()
            await session.commit()

        if job.kind == "population_generate":
            await _run_population_generate(job_id)
        else:
            async with factory() as session:
                await _fail(session, job_id, f"Unsupported job kind: {job.kind}")
    except Exception as exc:  # noqa: BLE001 — boundary: background worker
        logger.exception("Job %s failed", job_id)
        async with factory() as session:
            await _fail(session, job_id, str(exc) or exc.__class__.__name__)


async def _fail(session: AsyncSession, job_id: str, message: str) -> None:
    job = await session.get(Job, job_id)
    if job is None:
        return
    job.status = "failed"
    job.error = message[:2000]
    job.finished_at = utcnow()
    job.updated_at = utcnow()
    await session.commit()


async def _succeed(session: AsyncSession, job_id: str, result: dict) -> None:
    job = await session.get(Job, job_id)
    if job is None:
        return
    job.status = "succeeded"
    job.result = result
    job.error = None
    job.finished_at = utcnow()
    job.updated_at = utcnow()
    await session.commit()


async def _run_population_generate(job_id: str) -> None:
    factory = job_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        payload = PopulationGenerateJobRequest.model_validate(job.request)
        gen_req = PopulationGenerateRequest(recipe=payload.recipe, mode="replace")
        response = await gen.run_generate(gen_req, {}, session=session)

        if payload.population_id is not None:
            population = await update_population_from_generation(
                session,
                population_id=payload.population_id,
                name=payload.name,
                generation_id=response.generation_id,
                recipe=payload.recipe,
            )
        else:
            population = await create_population_from_generation(
                session,
                name=payload.name,
                generation_id=response.generation_id,
            )
        await session.commit()
        await _succeed(
            session,
            job_id,
            {
                "population_id": population.id,
                "fingerprint": response.fingerprint,
                "member_count": population.size,
            },
        )


async def list_jobs(
    session: AsyncSession,
    *,
    status: JobStatus | None = None,
    limit: int = 50,
) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(min(max(limit, 1), 100))
    if status is not None:
        stmt = stmt.where(Job.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_job(session: AsyncSession, job_id: str) -> Job | None:
    return await session.get(Job, job_id)


async def fail_interrupted_jobs(
    session: AsyncSession,
    *,
    message: str = "Avbrutet av serveromstart",
) -> int:
    """Mark pending/running jobs as failed on startup (no durable worker queue)."""
    now = utcnow()
    result = await session.execute(
        update(Job)
        .where(Job.status.in_(("pending", "running")))
        .values(
            status="failed",
            error=message,
            finished_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    return int(result.rowcount or 0)


# Hook for tests that want to await worker completion without racing create_task.
_schedule_hook: Callable[[str], None] | None = None


def set_schedule_hook(hook: Callable[[str], None] | None) -> None:
    global _schedule_hook
    _schedule_hook = hook


def enqueue_job(job_id: str) -> None:
    if _schedule_hook is not None:
        _schedule_hook(job_id)
        return
    schedule_job(job_id)
