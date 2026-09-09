"""Persisted rättsunderlag körningar (draft → research job → result)."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, RattsunderlagSession
from app.serializers import utcnow
from app.schemas.domain import format_date
from app.services.rattsunderlag.schemas import (
    RattsunderlagSessionCreate,
    RattsunderlagSessionOut,
    RattsunderlagSessionStatus,
    RattsunderlagSessionSummary,
    RattsunderlagSessionUpdate,
)


def new_rattsunderlag_session_id() -> str:
    return f"rus_{secrets.token_hex(8)}"


def topic_from_session(title: str, fraga: str) -> str:
    if title.strip():
        return title.strip()[:4000]
    first_line = next((line.strip() for line in fraga.splitlines() if line.strip()), "")
    return (first_line or "Rättsunderlag")[:4000]


def serialize_session(row: RattsunderlagSession) -> RattsunderlagSessionOut:
    locale = row.locale if row.locale in {"sv", "en"} else "sv"
    return RattsunderlagSessionOut(
        id=row.id,
        title=row.title,
        fraga=row.fraga,
        locale=locale,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        job_id=row.job_id,
        report_id=row.report_id,
        underlag_id=row.underlag_id,
        error=row.error,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


def serialize_summary(row: RattsunderlagSession) -> RattsunderlagSessionSummary:
    return RattsunderlagSessionSummary(
        id=row.id,
        title=row.title,
        topic=topic_from_session(row.title, row.fraga),
        status=row.status,  # type: ignore[arg-type]
        job_id=row.job_id,
        report_id=row.report_id,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


async def list_sessions(
    session: AsyncSession,
    *,
    customer_id: int | None,
    owner_user_id: str,
) -> list[RattsunderlagSessionSummary]:
    query = select(RattsunderlagSession).where(
        RattsunderlagSession.owner_user_id == owner_user_id
    )
    if customer_id is not None:
        query = query.where(RattsunderlagSession.customer_id == customer_id)
    query = query.order_by(RattsunderlagSession.updated_at.desc())
    result = await session.execute(query)
    return [serialize_summary(row) for row in result.scalars().all()]


async def get_session(
    session: AsyncSession, session_id: str
) -> RattsunderlagSession | None:
    row = await session.get(RattsunderlagSession, session_id)
    if row is not None:
        return row
    result = await session.execute(
        select(RattsunderlagSession).where(RattsunderlagSession.job_id == session_id)
    )
    return result.scalar_one_or_none()


async def get_research_job(session: AsyncSession, source_id: str) -> Job | None:
    job = await session.get(Job, source_id)
    if job is not None:
        return job
    row = await get_session(session, source_id)
    if row is None or not row.job_id:
        return None
    return await session.get(Job, row.job_id)


async def create_session(
    session: AsyncSession,
    body: RattsunderlagSessionCreate,
    *,
    customer_id: int,
    owner_user_id: str,
) -> RattsunderlagSessionOut:
    row = RattsunderlagSession(
        id=new_rattsunderlag_session_id(),
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        title=body.title,
        fraga=body.fraga,
        locale=body.locale,
        status="draft",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return serialize_session(row)


async def update_session(
    session: AsyncSession,
    row: RattsunderlagSession,
    body: RattsunderlagSessionUpdate,
) -> RattsunderlagSessionOut:
    if row.status in {"pending", "running"}:
        raise RuntimeError("Cannot edit a running rättsunderlag session")
    if body.fraga is not None:
        row.fraga = body.fraga
    if body.title is not None:
        row.title = body.title
    if body.locale is not None:
        row.locale = body.locale
    if row.status == "failed":
        row.status = "draft"
        row.error = None
    row.updated_at = utcnow()
    await session.flush()
    return serialize_session(row)


async def delete_session(session: AsyncSession, row: RattsunderlagSession) -> None:
    if row.status in {"pending", "running"}:
        raise RuntimeError("Cannot delete a running rättsunderlag session")
    await session.delete(row)


def prepare_session_for_run(row: RattsunderlagSession) -> None:
    if not row.fraga.strip():
        raise ValueError("fraga is required")
    if row.status in {"pending", "running"}:
        raise RuntimeError("Rättsunderlag session already running")


async def apply_job_status(
    session: AsyncSession,
    *,
    session_id: str | None,
    job_id: str,
    status: RattsunderlagSessionStatus,
    error: str | None = None,
    report_id: str | None = None,
    underlag_id: str | None = None,
) -> None:
    row: RattsunderlagSession | None = None
    if session_id:
        row = await session.get(RattsunderlagSession, session_id)
    if row is None:
        result = await session.execute(
            select(RattsunderlagSession).where(RattsunderlagSession.job_id == job_id)
        )
        row = result.scalar_one_or_none()
    if row is None:
        return
    row.status = status
    row.job_id = job_id
    row.updated_at = utcnow()
    if error is not None:
        row.error = error[:2000]
    elif status != "failed":
        row.error = None
    if report_id is not None:
        row.report_id = report_id
    if underlag_id is not None:
        row.underlag_id = underlag_id
    await session.flush()
