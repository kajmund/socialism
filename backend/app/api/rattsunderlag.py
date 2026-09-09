"""Rättsunderlag API — sessions, research jobs, and results."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access, customer_id_for_user, effective_customer_id
from app.database.models import Job, RattsunderlagSession, UserAccount
from app.database.session import get_session
from app.schemas.domain import JobCreate, JobOut
from app.services import jobs as jobs_service
from app.services.rattsunderlag import JOB_KIND
from app.services.rattsunderlag.schemas import (
    RattsunderlagSessionCreate,
    RattsunderlagSessionOut,
    RattsunderlagSessionSummary,
    RattsunderlagSessionUpdate,
    RattsunderlagStart,
)
from app.services.rattsunderlag.sessions import (
    create_session,
    delete_session,
    get_session as load_session,
    list_sessions,
    prepare_session_for_run,
    serialize_session,
    topic_from_session,
    update_session,
)

router = APIRouter(prefix="/rattsunderlag", tags=["rattsunderlag"])


def _owner_matches(job: Job, user_id: str) -> bool:
    request = job.request if isinstance(job.request, dict) else {}
    return str(request.get("owner_user_id") or "") == user_id


async def _require_session(
    session: AsyncSession,
    user: UserAccount,
    session_id: str,
) -> RattsunderlagSession:
    row = await load_session(session, session_id)
    if row is None or row.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Rättsunderlag session not found")
    assert_kund_access(user, row.customer_id)
    return row


async def _start_session_job(
    session: AsyncSession,
    row: RattsunderlagSession,
) -> Job:
    prepare_session_for_run(row)
    row.status = "pending"
    row.error = None
    row.report_id = None
    row.underlag_id = None
    await session.flush()
    label = topic_from_session(row.title, row.fraga)
    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind=JOB_KIND,
            label=f"Rättsunderlag: {label[:80]}",
            request={
                "fraga": row.fraga,
                "customer_id": row.customer_id,
                "owner_user_id": row.owner_user_id,
                "locale": row.locale,
                "session_id": row.id,
            },
        ),
    )
    row.job_id = job.id
    await session.commit()
    jobs_service.enqueue_job(job.id)
    return job


@router.get("/sessions", response_model=list[RattsunderlagSessionSummary])
async def get_rattsunderlag_sessions(
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[RattsunderlagSessionSummary]:
    customer_id = effective_customer_id(user)
    return await list_sessions(
        session, customer_id=customer_id, owner_user_id=user.id
    )


@router.post("/sessions", response_model=RattsunderlagSessionOut, status_code=201)
async def post_rattsunderlag_session(
    body: RattsunderlagSessionCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> RattsunderlagSessionOut:
    customer_id = await customer_id_for_user(session, user)
    out = await create_session(
        session, body, customer_id=customer_id, owner_user_id=user.id
    )
    await session.commit()
    return out


@router.get("/sessions/{session_id}", response_model=RattsunderlagSessionOut)
async def get_rattsunderlag_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> RattsunderlagSessionOut:
    row = await _require_session(session, user, session_id)
    return serialize_session(row)


@router.patch("/sessions/{session_id}", response_model=RattsunderlagSessionOut)
async def patch_rattsunderlag_session(
    session_id: str,
    body: RattsunderlagSessionUpdate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> RattsunderlagSessionOut:
    row = await _require_session(session, user, session_id)
    try:
        out = await update_session(session, row, body)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return out


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_rattsunderlag_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    row = await _require_session(session, user, session_id)
    try:
        await delete_session(session, row)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return Response(status_code=204)


@router.post("/sessions/{session_id}/run", status_code=202)
async def post_rattsunderlag_session_run(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, str]:
    row = await _require_session(session, user, session_id)
    try:
        job = await _start_session_job(session, row)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job.id, "session_id": row.id}


@router.post("/research", response_model=JobOut, status_code=202)
async def post_rattsunderlag_research(
    body: RattsunderlagStart,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> JobOut:
    customer_id = await customer_id_for_user(session, user)
    created = await create_session(
        session,
        RattsunderlagSessionCreate(fraga=body.fraga, locale=body.locale),
        customer_id=customer_id,
        owner_user_id=user.id,
    )
    row = await load_session(session, created.id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create session")
    job = await _start_session_job(session, row)
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
