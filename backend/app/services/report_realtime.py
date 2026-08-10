"""Serialize + publish report list events over WebSocket."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.realtime.hub import report_hub
from app.schemas.domain import ReportOut
from app.services.report.locale import normalize_locale


def _normalize_mode(value: str | None) -> str:
    return "quick" if value == "quick" else "full"


def serialize_report(report: Report) -> ReportOut:
    return ReportOut(
        id=report.id,
        status=report.status,  # type: ignore[arg-type]
        title=report.title,
        locale=normalize_locale(getattr(report, "locale", None)),
        mode=_normalize_mode(getattr(report, "mode", None)),  # type: ignore[arg-type]
        sources=list(report.sources or []),
        html_path=report.html_path,
        slots_path=report.slots_path,
        job_id=report.job_id,
        error=report.error,
        created_at=report.created_at.isoformat() if report.created_at else "",
        finished_at=report.finished_at.isoformat() if report.finished_at else None,
        updated_at=report.updated_at.isoformat() if report.updated_at else "",
    )


async def list_reports(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[Report]:
    stmt = select(Report).order_by(Report.created_at.desc()).limit(min(max(limit, 1), 100))
    if status is not None:
        stmt = stmt.where(Report.status == status)
    return list((await session.execute(stmt)).scalars().all())


async def publish_report(report: Report) -> None:
    await report_hub.publish(
        {
            "type": "report.updated",
            "report": serialize_report(report).model_dump(mode="json"),
        }
    )


async def publish_reports_deleted(ids: list[str]) -> None:
    if not ids:
        return
    await report_hub.publish({"type": "report.deleted", "ids": list(ids)})
