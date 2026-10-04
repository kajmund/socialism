"""Background jobs API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import (
    assert_kund_access,
    effective_customer_id,
)
from app.database.models import UserAccount
from app.database.session import get_session
from app.schemas.domain import JobArchiveUpdate, JobCreate, JobOut, JobStatus
from app.services import jobs as jobs_service
from app.services.customer_scope import customer_id_for_new_job
from app.services.workspace_api_scope import (
    archive_visible_workspace_jobs, require_job_scope, validate_new_workspace_job, visible_workspace_jobs,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobOut, status_code=202)
async def create_job(
    body: JobCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    if body.kind == "workspace_generation":
        raise HTTPException(status_code=422, detail="use_workspace_tools_to_create_generation_jobs")
    try:
        customer_id = await customer_id_for_new_job(session, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assert_kund_access(user, customer_id)
    await validate_new_workspace_job(session, user, customer_id, body)
    try:
        job = await jobs_service.create_job(session, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    jobs_service.enqueue_job(job.id)
    response.status_code = 202
    return jobs_service.serialize_job(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(  # noqa: PLR0917
    status: JobStatus | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    include_archived: bool = Query(default=False),
    archived_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[JobOut]:
    customer_id = effective_customer_id(user, customer_id)
    rows = await jobs_service.list_jobs(
        session,
        status=status,
        customer_id=customer_id,
        limit=limit,
        include_archived=include_archived or archived_only,
        archived_only=archived_only,
    )
    return [jobs_service.serialize_job(row) for row in await visible_workspace_jobs(session, user, rows)]


@router.post("/archive-finished", response_model=list[JobOut])
async def archive_finished_jobs(
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[JobOut]:
    customer_id = effective_customer_id(user, None)
    rows = await archive_visible_workspace_jobs(session, user, customer_id)
    return [jobs_service.serialize_job(row) for row in rows]


@router.post("/{job_id}/resume", response_model=JobOut)
async def resume_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    job = await require_job_scope(session, user, job_id)
    try:
        job = await jobs_service.resume_failed_job(session, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    jobs_service.enqueue_job(job.id)
    return jobs_service.serialize_job(job)


@router.post("/{job_id}/rerun", response_model=JobOut, status_code=202)
async def rerun_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    job = await require_job_scope(session, user, job_id)
    try:
        created = await jobs_service.rerun_finished_job(session, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    jobs_service.enqueue_job(created.id)
    return jobs_service.serialize_job(created)


@router.patch("/{job_id}", response_model=JobOut)
async def patch_job(
    job_id: str,
    body: JobArchiveUpdate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    job = await require_job_scope(session, user, job_id)
    try:
        job = await jobs_service.set_job_archived(session, job, body.archived)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return jobs_service.serialize_job(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    job = await require_job_scope(session, user, job_id)
    return jobs_service.serialize_job(job)
