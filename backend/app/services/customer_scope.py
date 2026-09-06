"""Resolve customer_id when creating scoped rows (jobs, reports)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DdCampaign, Job, PanelSession, Projekt, Report, Run
from app.schemas.domain import (
    JobCreate,
    PopulationGenerateJobRequest,
    ReportCreate,
    ReportGenerateJobRequest,
    RunSimulateJobRequest,
)
from app.services.dd.schemas import DdResearchJobRequest
from app.services.rattsunderlag.schemas import RattsunderlagResearchJobRequest
from app.services.kund_store import bolag_demo_customer_id, default_os_customer_id
from app.services.panel.schemas import PanelSessionRunJobRequest


async def customer_id_for_run(session: AsyncSession, run_id: int) -> int:
    run = await session.get(Run, run_id)
    if run is None:
        return await default_os_customer_id(session)
    projekt = await session.get(Projekt, run.project_id)
    if projekt is None:
        return await default_os_customer_id(session)
    return projekt.customer_id


async def customer_id_for_panel_session(session: AsyncSession, session_id: str) -> int:
    """Resolve tenant for a panel job/report.

    Prefer ``project_id`` (module-agnostic) over ``campaign_id`` (DD extra).
    A set ``project_id`` whose row is missing fails loud — SQLite may not
    enforce the FK, and falling through would assign the wrong tenant.
    """
    panel = await session.get(PanelSession, session_id)
    if panel is None:
        return await default_os_customer_id(session)
    if panel.project_id is not None:
        projekt = await session.get(Projekt, panel.project_id)
        if projekt is None:
            raise RuntimeError(
                f"Panel session {session_id!r} references missing project_id={panel.project_id}"
            )
        return projekt.customer_id
    if panel.campaign_id is not None:
        campaign = await session.get(DdCampaign, panel.campaign_id)
        if campaign is not None:
            return campaign.customer_id
    return await default_os_customer_id(session)


async def customer_id_for_new_report(
    session: AsyncSession,
    body: ReportCreate,
    *,
    sources: list[dict],
    mode: str,
) -> int:
    if body.sources and body.sources[0].type == "rattsunderlag":
        job = await session.get(Job, body.sources[0].session_id or "")
        if job is None:
            return await default_os_customer_id(session)
        return job.customer_id
    if body.sources and (body.sources[0].session_id or "").strip():
        return await customer_id_for_panel_session(session, body.sources[0].session_id or "")
    if sources and sources[0].get("type") == "oasis":
        run_id = sources[0].get("run_id")
        if isinstance(run_id, int):
            return await customer_id_for_run(session, run_id)
    return await default_os_customer_id(session)


async def customer_id_for_new_job(session: AsyncSession, body: JobCreate) -> int:
    if body.kind == "population_generate":
        payload = PopulationGenerateJobRequest.model_validate(body.request)
        if payload.kind == "expert_panel":
            if payload.customer_id is not None:
                return payload.customer_id
            return await bolag_demo_customer_id(session)
        return await default_os_customer_id(session)
    if body.kind == "run_simulate":
        payload = RunSimulateJobRequest.model_validate(body.request)
        return await customer_id_for_run(session, payload.run_id)
    if body.kind == "report_generate":
        payload = ReportGenerateJobRequest.model_validate(body.request)
        report = await session.get(Report, payload.report_id)
        if report is None:
            return await default_os_customer_id(session)
        return report.customer_id
    if body.kind == "panel_session_run":
        payload = PanelSessionRunJobRequest.model_validate(body.request)
        return await customer_id_for_panel_session(session, payload.session_id)
    if body.kind == "dd_research":
        payload = DdResearchJobRequest.model_validate(body.request)
        campaign = await session.get(DdCampaign, payload.campaign_id)
        if campaign is None:
            return await default_os_customer_id(session)
        return campaign.customer_id
    if body.kind == "rattsunderlag_research":
        payload = RattsunderlagResearchJobRequest.model_validate(body.request)
        return payload.customer_id
    return await default_os_customer_id(session)
