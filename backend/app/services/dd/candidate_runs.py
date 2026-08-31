"""Persist candidate → panel session → report links for DD campaigns."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DdCandidateRun, PanelSession
from app.serializers import format_date
from app.services.dd.schemas import DdCandidateRunOut, DdResearchDossier


def serialize_candidate_run(row: DdCandidateRun) -> DdCandidateRunOut:
    research = None
    if isinstance(row.research, dict) and row.research:
        research = DdResearchDossier.model_validate(row.research)
    return DdCandidateRunOut(
        candidate_id=row.candidate_id,
        panel_session_id=row.panel_session_id,
        report_id=row.report_id,
        research=research,
        research_job_id=row.research_job_id,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
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
        row.report_id = None
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


async def upsert_research_job(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
    job_id: str,
) -> DdCandidateRunOut:
    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    if row is None:
        row = DdCandidateRun(
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            panel_session_id=None,
            report_id=None,
            research_job_id=job_id,
        )
        session.add(row)
    else:
        row.research_job_id = job_id
    await session.flush()
    await session.refresh(row)
    return serialize_candidate_run(row)


async def upsert_research(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
    dossier: DdResearchDossier,
    job_id: str,
) -> DdCandidateRunOut:
    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    payload = dossier.model_dump(mode="json")
    if row is None:
        row = DdCandidateRun(
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            panel_session_id=None,
            report_id=None,
            research=payload,
            research_job_id=job_id,
        )
        session.add(row)
    else:
        row.research = payload
        row.research_job_id = job_id
    await session.flush()
    await session.refresh(row)
    return serialize_candidate_run(row)


async def clear_research(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
) -> DdCandidateRunOut | None:
    """Drop the research dossier; keep panel/report links on the run row."""
    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    if row is None:
        return None
    row.research = None
    row.research_job_id = None
    await session.flush()
    await session.refresh(row)
    return serialize_candidate_run(row)


async def delete_candidate_run(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
) -> bool:
    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    if row is None:
        return False
    if row.panel_session_id:
        await session.execute(
            update(PanelSession)
            .where(PanelSession.id == row.panel_session_id)
            .values(campaign_id=None)
        )
    await session.delete(row)
    return True
