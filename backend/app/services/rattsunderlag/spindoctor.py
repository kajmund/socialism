"""Minimal Spinndoktor binding so report chat does not crash."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, Report
from app.modules.manifest import SpindoctorSource
from app.services.rattsunderlag import SOURCE_TYPE
from app.services.rattsunderlag.schemas import RattsunderlagResult
from app.services.report.rattsutredning import render_rattsutredning_markdown


def _job_id_from_report(report: Report) -> str:
    sources = report.sources if isinstance(report.sources, list) else []
    if not sources or not isinstance(sources[0], dict):
        raise ValueError("Rättsunderlag report is missing sources")
    source = sources[0]
    if source.get("type") != SOURCE_TYPE:
        raise ValueError(f"Unexpected report source type: {source.get('type')}")
    job_id = str(source.get("session_id") or "").strip()
    if not job_id:
        raise ValueError("Rättsunderlag report source is missing session_id")
    return job_id


async def load_rattsunderlag_spindoctor_source(
    session: AsyncSession,
    report: Report,
) -> SpindoctorSource:
    job = await session.get(Job, _job_id_from_report(report))
    if job is None:
        raise ValueError("Rättsunderlag research job not found")
    raw = job.result if isinstance(job.result, dict) else None
    payload = raw.get("result") if raw else None
    if not isinstance(payload, dict):
        raise ValueError("Rättsunderlag research job has no result")
    return SpindoctorSource(report=report, payload=payload)


def build_rattsunderlag_spindoctor_context_from_source(
    source: SpindoctorSource,
    *,
    locale: str,
    title: str,
) -> str:
    result = RattsunderlagResult.model_validate(source.payload)
    memo = render_rattsutredning_markdown(result.as_payload(), locale=locale)
    heading = title.strip() or "Rättsunderlag"
    return f"{heading}\n\n{memo}"
