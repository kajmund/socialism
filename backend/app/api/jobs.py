"""Background jobs API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.domain import JobCreate, JobOut, JobStatus
from app.services import jobs as jobs_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobOut, status_code=202)
async def create_job(
    body: JobCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    try:
        job = await jobs_service.create_job(session, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    jobs_service.enqueue_job(job.id)
    response.status_code = 202
    return jobs_service.serialize_job(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    status: JobStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[JobOut]:
    rows = await jobs_service.list_jobs(session, status=status, limit=limit)
    return [jobs_service.serialize_job(row) for row in rows]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    job = await jobs_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs_service.serialize_job(job)
