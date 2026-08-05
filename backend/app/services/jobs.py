"""Background job create / run / query."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.models import Job, Report, Run
from app.database.session import SessionLocal
from app.schemas.domain import (
    JobCreate,
    JobOut,
    JobStatus,
    PopulationGenerateJobRequest,
    PopulationGenerateRequest,
    ReportGenerateJobRequest,
    RunSimulateJobRequest,
)
from app.serializers import utcnow
from app.services import population_generate as gen
from app.services.oasis_run import (
    OasisUnavailable,
    attempt_all_failed,
    build_empty_attempt,
    merge_attempt,
    oasis_installed,
    previous_attempts,
    simulate_run,
)
from app.services.population_persist import (
    create_population_from_generation,
    update_population_from_generation,
)

logger = logging.getLogger(__name__)

_session_factory: async_sessionmaker[AsyncSession] | None = None
_simulation_job_semaphore: asyncio.Semaphore | None = None
_simulation_job_semaphore_limit: int | None = None


def set_job_session_factory(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Tests inject an in-memory session factory; production uses SessionLocal."""
    global _session_factory
    _session_factory = factory


def job_session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory or SessionLocal


def reset_simulation_job_semaphore() -> None:
    """Drop cached semaphore (tests change max_concurrent_simulation_jobs)."""
    global _simulation_job_semaphore, _simulation_job_semaphore_limit
    _simulation_job_semaphore = None
    _simulation_job_semaphore_limit = None


def simulation_job_semaphore() -> asyncio.Semaphore:
    """Process-wide cap on overlapping run_simulate workers."""
    global _simulation_job_semaphore, _simulation_job_semaphore_limit
    limit = settings.max_concurrent_simulation_jobs
    if _simulation_job_semaphore is None or _simulation_job_semaphore_limit != limit:
        _simulation_job_semaphore = asyncio.Semaphore(limit)
        _simulation_job_semaphore_limit = limit
    return _simulation_job_semaphore


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
        label = (body.label or "").strip() or str(body.request.get("name") or "Jobb")
    elif body.kind == "run_simulate":
        payload = RunSimulateJobRequest.model_validate(body.request)
        run = await session.get(Run, payload.run_id)
        if run is None:
            raise ValueError(f"Run not found: {payload.run_id}")
        label = (body.label or "").strip() or run.name
    elif body.kind == "report_generate":
        payload = ReportGenerateJobRequest.model_validate(body.request)
        report = await session.get(Report, payload.report_id)
        if report is None:
            raise ValueError(f"Report not found: {payload.report_id}")
        label = (body.label or "").strip() or report.title or payload.report_id
    else:
        raise ValueError(f"Unsupported job kind: {body.kind}")

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
    async def _deferred() -> None:
        # Yield so the HTTP handler can finish (e.g. 202 on /runs/{id}/start)
        # before heavy OASIS work contends for the event loop.
        await asyncio.sleep(0)
        await _run_job(job_id)

    asyncio.create_task(_deferred(), name=f"job:{job_id}")


async def _mark_job_running(job_id: str) -> str | None:
    """Transition pending/running → running. Returns kind, or None if skipped."""
    factory = job_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return None
        if job.status not in {"pending", "running"}:
            return None
        job.status = "running"
        job.started_at = utcnow()
        job.updated_at = utcnow()
        await session.commit()
        return job.kind


async def _execute_job_kind(job_id: str, kind: str) -> None:
    if kind == "population_generate":
        await _run_population_generate(job_id)
    elif kind == "run_simulate":
        await _run_simulate(job_id)
    elif kind == "report_generate":
        await _run_report_generate(job_id)
    else:
        factory = job_session_factory()
        async with factory() as session:
            await _fail(session, job_id, f"Unsupported job kind: {kind}")


async def _run_job(job_id: str) -> None:
    factory = job_session_factory()
    try:
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            if job.status not in {"pending", "running"}:
                return
            kind = job.kind

        # Keep run_simulate pending until a simulation slot is free so the UI
        # does not show many "running" jobs that are only waiting on the cap.
        if kind == "run_simulate":
            async with simulation_job_semaphore():
                marked = await _mark_job_running(job_id)
                if marked is None:
                    return
                await _execute_job_kind(job_id, marked)
            return

        marked = await _mark_job_running(job_id)
        if marked is None:
            return
        await _execute_job_kind(job_id, marked)
    except Exception as exc:
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
        library = await gen.load_library_personas(session, payload.include_persona_ids)
        gen_req = PopulationGenerateRequest(
            recipe=payload.recipe,
            include_persona_ids=payload.include_persona_ids,
            mode="replace",
        )
        response = await gen.run_generate(gen_req, library, session=session)

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
                "warnings": response.warnings,
            },
        )


async def _run_simulate(job_id: str) -> None:
    factory = job_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        payload = RunSimulateJobRequest.model_validate(job.request)
        run = await session.get(Run, payload.run_id)
        if run is None:
            await _fail(session, job_id, f"Run not found: {payload.run_id}")
            return

        if settings.simulation_engine != "oasis":
            attempt = build_empty_attempt(run, engine=settings.simulation_engine)
            await session.refresh(run)
            run.results = merge_attempt(
                run.results if isinstance(run.results, dict) else None,
                attempt,
                engine=settings.simulation_engine,
            )
            run.status = "done"
            run.updated_at = utcnow()
            await session.commit()
            await _succeed(
                session,
                job_id,
                {
                    "run_id": run.id,
                    "engine": settings.simulation_engine,
                    "variants": len(attempt.get("variants") or []),
                    "attempts": len(previous_attempts(run.results)),
                },
            )
            return

        if not settings.deepseek_api_key:
            msg = "DEEPSEEK_API_KEY is required when SIMULATION_ENGINE=oasis"
            attempt = build_empty_attempt(run, engine="oasis", error=msg)
            await session.refresh(run)
            run.results = merge_attempt(
                run.results if isinstance(run.results, dict) else None,
                attempt,
                engine="oasis",
            )
            run.status = "failed"
            run.updated_at = utcnow()
            await session.commit()
            await _fail(session, job_id, msg)
            return
        if not oasis_installed():
            msg = "camel-oasis is not installed. Run: uv sync --extra oasis"
            attempt = build_empty_attempt(run, engine="oasis", error=msg)
            await session.refresh(run)
            run.results = merge_attempt(
                run.results if isinstance(run.results, dict) else None,
                attempt,
                engine="oasis",
            )
            run.status = "failed"
            run.updated_at = utcnow()
            await session.commit()
            await _fail(session, job_id, msg)
            return

        try:
            results = await simulate_run(session, run)
            latest = (results.get("attempts") or [{}])[0]
            run.status = "failed" if attempt_all_failed(latest) else "done"
            run.results = results
            run.updated_at = utcnow()
            await session.commit()
            await _succeed(
                session,
                job_id,
                {
                    "run_id": run.id,
                    "engine": "oasis",
                    "variants": len(latest.get("variants") or []),
                    "attempts": len(results.get("attempts") or []),
                    "ticks_run": sum(
                        (v.get("ticks_run") or 0) for v in (latest.get("variants") or [])
                    ),
                },
            )
        except OasisUnavailable as exc:
            attempt = build_empty_attempt(run, engine="oasis", error=str(exc))
            await session.refresh(run)
            run.results = merge_attempt(
                run.results if isinstance(run.results, dict) else None,
                attempt,
                engine="oasis",
            )
            run.status = "failed"
            run.updated_at = utcnow()
            await session.commit()
            await _fail(session, job_id, str(exc))
        except Exception as exc:  # noqa: BLE001 — mark run failed for any OASIS/LLM error
            attempt = build_empty_attempt(
                run, engine="oasis", error=str(exc) or exc.__class__.__name__
            )
            await session.refresh(run)
            run.results = merge_attempt(
                run.results if isinstance(run.results, dict) else None,
                attempt,
                engine="oasis",
            )
            run.status = "failed"
            run.updated_at = utcnow()
            await session.commit()
            await _fail(session, job_id, str(exc) or exc.__class__.__name__)


async def _run_report_generate(job_id: str) -> None:
    from pathlib import Path

    from app.services.report import ARTIFACT_ROOT
    from app.services.report.bundles import build_bundles
    from app.services.report.generate import generate_report_html

    factory = job_session_factory()
    report_id: str | None = None
    title = ""
    sources: list = []
    out_dir: Path | None = None

    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        payload = ReportGenerateJobRequest.model_validate(job.request)
        report = await session.get(Report, payload.report_id)
        if report is None:
            await _fail(session, job_id, f"Report not found: {payload.report_id}")
            return

        report_id = report.id
        title = report.title
        sources = list(report.sources or [])
        report.status = "running"
        report.updated_at = utcnow()
        await session.commit()

        # Build bundles while session is open, then release before long LLM work.
        bundles = await build_bundles(session, sources)
        out_dir = Path(ARTIFACT_ROOT) / report_id

    try:
        html_path, slots_path, _slots = await generate_report_html(
            bundles,
            out_dir=out_dir,
            dry_run=False,
            title=title,
        )
    except Exception as exc:  # noqa: BLE001 — mark report failed
        async with factory() as session:
            report = await session.get(Report, report_id)
            if report is not None:
                report.status = "failed"
                report.error = (str(exc) or exc.__class__.__name__)[:2000]
                report.finished_at = utcnow()
                report.updated_at = utcnow()
                await session.commit()
            await _fail(session, job_id, str(exc) or exc.__class__.__name__)
        return

    async with factory() as session:
        report = await session.get(Report, report_id)
        if report is None:
            await _fail(session, job_id, f"Report disappeared: {report_id}")
            return
        report.status = "succeeded"
        report.html_path = str(html_path)
        report.slots_path = str(slots_path)
        report.error = None
        report.finished_at = utcnow()
        report.updated_at = utcnow()
        await session.commit()
        await _succeed(
            session,
            job_id,
            {
                "report_id": report.id,
                "html_path": str(html_path),
                "slots_path": str(slots_path),
                "sources": len(bundles),
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
    active = await session.execute(
        select(Job).where(Job.status.in_(("pending", "running")))
    )
    run_ids: list[int] = []
    report_ids: list[str] = []
    for job in active.scalars().all():
        if job.kind == "run_simulate":
            rid = (job.request or {}).get("run_id")
            if isinstance(rid, int):
                run_ids.append(rid)
        elif job.kind == "report_generate":
            rid = (job.request or {}).get("report_id")
            if isinstance(rid, str):
                report_ids.append(rid)

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
    if run_ids:
        for run_id in run_ids:
            run = await session.get(Run, run_id)
            if run is None or run.status != "running":
                continue
            attempt = build_empty_attempt(run, engine=settings.simulation_engine, error=message)
            await session.refresh(run)
            run.results = merge_attempt(
                run.results if isinstance(run.results, dict) else None,
                attempt,
                engine=settings.simulation_engine,
            )
            run.status = "failed"
            run.updated_at = now
    for report_id in report_ids:
        report = await session.get(Report, report_id)
        if report is None or report.status not in {"pending", "running"}:
            continue
        report.status = "failed"
        report.error = message
        report.finished_at = now
        report.updated_at = now
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
