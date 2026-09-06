"""Rättsunderlag API — start research jobs and read results."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access, customer_id_for_user
from app.database.models import Job, UserAccount
from app.database.session import get_session
from app.schemas.domain import JobCreate, JobOut
from app.services import jobs as jobs_service
from app.services.rattsunderlag import JOB_KIND
from app.services.rattsunderlag.schemas import RattsunderlagStart

router = APIRouter(prefix="/rattsunderlag", tags=["rattsunderlag"])


def _owner_matches(job: Job, user_id: str) -> bool:
    request = job.request if isinstance(job.request, dict) else {}
    return str(request.get("owner_user_id") or "") == user_id


@router.post("/research", response_model=JobOut, status_code=202)
async def post_rattsunderlag_research(
    body: RattsunderlagStart,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    customer_id = await customer_id_for_user(session, user)
    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind=JOB_KIND,
            label=f"Rättsunderlag: {body.fraga[:80]}",
            request={
                "fraga": body.fraga,
                "customer_id": customer_id,
                "owner_user_id": user.id,
                "locale": body.locale,
            },
        ),
    )
    jobs_service.enqueue_job(job.id)
    return jobs_service.serialize_job(job)


@router.get("/research", response_model=list[JobOut])
async def list_rattsunderlag_research(
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[JobOut]:
    customer_id = await customer_id_for_user(session, user)
    result = await session.execute(
        select(Job)
        .where(Job.customer_id == customer_id, Job.kind == JOB_KIND)
        .order_by(Job.created_at.desc())
        .limit(50)
    )
    rows = [job for job in result.scalars().all() if _owner_matches(job, user.id)]
    return [jobs_service.serialize_job(job) for job in rows]


@router.get("/research/{job_id}", response_model=JobOut)
async def get_rattsunderlag_research(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None or job.kind != JOB_KIND or not _owner_matches(job, user.id):
        raise HTTPException(status_code=404, detail="Research job not found")
    assert_kund_access(user, job.customer_id)
    return jobs_service.serialize_job(job)
