"""Persist candidate → panel session → report links for DD campaigns."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DdCandidateRun, PanelSession, Report
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


async def _upsert_candidate_run(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
    panel_session_id: str | None = None,
    report_id: str | None = None,
    clear_report: bool = False,
) -> DdCandidateRunOut:
    """Insert or update candidate run links atomically (SQLite upsert; phase-1 DB)."""
    insert_values: dict[str, object] = {
        "campaign_id": campaign_id,
        "candidate_id": candidate_id,
    }
    update_values: dict[str, object] = {}
    if panel_session_id is not None:
        insert_values["panel_session_id"] = panel_session_id
        update_values["panel_session_id"] = panel_session_id
    if report_id is not None:
        insert_values["report_id"] = report_id
        update_values["report_id"] = report_id
    if clear_report:
        insert_values["report_id"] = None
        update_values["report_id"] = None

    stmt = sqlite_insert(DdCandidateRun).values(**insert_values)
    if update_values:
        stmt = stmt.on_conflict_do_update(
            index_elements=["campaign_id", "candidate_id"],
            set_=update_values,
        )
    await session.execute(stmt)
    await session.flush()

    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    if row is None:
        raise RuntimeError(
            f"candidate run missing after upsert: campaign={campaign_id} candidate={candidate_id}"
        )
    return serialize_candidate_run(row)


async def upsert_panel_session(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
    panel_session_id: str,
) -> DdCandidateRunOut:
    existing = await get_candidate_run(
        session, campaign_id=campaign_id, candidate_id=candidate_id
    )
    return await _upsert_candidate_run(
        session,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        panel_session_id=panel_session_id,
        clear_report=existing is not None,
    )


async def upsert_report(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
    report_id: str,
) -> DdCandidateRunOut:
    return await _upsert_candidate_run(
        session,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        report_id=report_id,
    )


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
) -> tuple[bool, str | None]:
    """Delete the candidate-run link and its panel session.

    Returns ``(removed, report_id)``. ``report_id`` is set when a linked report
    row was deleted (caller should remove on-disk artifacts after commit).
    """
    row = await get_candidate_run(session, campaign_id=campaign_id, candidate_id=candidate_id)
    if row is None:
        return False, None
    panel_id = row.panel_session_id
    report_id = row.report_id
    await session.delete(row)
    await session.flush()
    if panel_id:
        panel = await session.get(PanelSession, panel_id)
        if panel is not None:
            await session.delete(panel)
            await session.flush()
    deleted_report_id: str | None = None
    if report_id:
        report = await session.get(Report, report_id)
        if report is not None:
            await session.delete(report)
            deleted_report_id = report_id
            await session.flush()
    return True, deleted_report_id
