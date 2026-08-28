"""Resolve customer_id when creating scoped rows (jobs, reports)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DdCampaign, PanelSession, Projekt, Report, Run
from app.schemas.domain import (
    JobCreate,
    ReportCreate,
    ReportGenerateJobRequest,
    RunSimulateJobRequest,
)
from app.services.kund_store import default_os_customer_id
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
    panel = await session.get(PanelSession, session_id)
    if panel is None or panel.campaign_id is None:
        return await default_os_customer_id(session)
    campaign = await session.get(DdCampaign, panel.campaign_id)
    if campaign is None:
        return await default_os_customer_id(session)
    return campaign.customer_id


async def customer_id_for_new_report(
    session: AsyncSession,
    body: ReportCreate,
    *,
    sources: list[dict],
    mode: str,
) -> int:
    if mode == "dd" and body.sources:
        return await customer_id_for_panel_session(session, body.sources[0].session_id or "")
    if sources and sources[0].get("type") == "oasis":
        run_id = sources[0].get("run_id")
        if isinstance(run_id, int):
            return await customer_id_for_run(session, run_id)
    return await default_os_customer_id(session)


async def customer_id_for_new_job(session: AsyncSession, body: JobCreate) -> int:
    if body.kind == "population_generate":
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
    return await default_os_customer_id(session)
