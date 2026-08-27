"""Persist candidate → panel session → report links for DD campaigns."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DdCandidateRun
from app.services.dd.schemas import DdCandidateRunOut


def serialize_candidate_run(row: DdCandidateRun) -> DdCandidateRunOut:
    return DdCandidateRunOut(
        candidate_id=row.candidate_id,
        panel_session_id=row.panel_session_id,
        report_id=row.report_id,
    )


async def list_run_candidate_ids(session: AsyncSession, campaign_id: int) -> set[str]:
    stmt = select(DdCandidateRun.candidate_id).where(DdCandidateRun.campaign_id == campaign_id)
    rows = (await session.execute(stmt)).scalars().all()
    return set(rows)


async def list_candidate_runs(session: AsyncSession, campaign_id: int) -> list[DdCandidateRunOut]:
    stmt = (
        select(DdCandidateRun)
        .where(DdCandidateRun.campaign_id == campaign_id)
        .order_by(DdCandidateRun.updated_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [serialize_candidate_run(row) for row in rows]


async def get_candidate_run(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
) -> DdCandidateRun | None:
    stmt = select(DdCandidateRun).where(
        DdCandidateRun.campaign_id == campaign_id,
        DdCandidateRun.candidate_id == candidate_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_panel_session(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
    panel_session_id: str,
) -> DdCandidateRunOut:
    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    if row is None:
        row = DdCandidateRun(
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            panel_session_id=panel_session_id,
            report_id=None,
        )
        session.add(row)
    else:
        row.panel_session_id = panel_session_id
    await session.flush()
    await session.refresh(row)
    return serialize_candidate_run(row)


async def upsert_report(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
    report_id: str,
) -> DdCandidateRunOut:
    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    if row is None:
        row = DdCandidateRun(
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            panel_session_id=None,
            report_id=report_id,
        )
        session.add(row)
    else:
        row.report_id = report_id
    await session.flush()
    await session.refresh(row)
    return serialize_candidate_run(row)
