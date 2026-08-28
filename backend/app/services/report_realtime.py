"""Serialize + publish report list events over WebSocket."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.realtime.hub import report_hub
from app.schemas.domain import ReportOut
from app.services.report.locale import normalize_locale


def _normalize_mode(value: str | None) -> str:
    """Pass through legacy ``full`` rows; recognize ``dd`` and default to ``quick``."""
    if value == "full":
        return "full"
    if value == "dd":
        return "dd"
    return "quick"


def _normalize_sources(raw: list | None) -> list[dict]:
    out: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "dd_session":
            out.append(
                {
                    "type": "dd_session",
                    "session_id": item.get("session_id"),
                    "candidate_id": item.get("candidate_id"),
                }
            )
        else:
            out.append(
                {
                    "type": "oasis",
                    "run_id": item.get("run_id"),
                    "attempt_id": item.get("attempt_id"),
                }
            )
    return out


def serialize_report(report: Report) -> ReportOut:
    return ReportOut(
        id=report.id,
        customer_id=report.customer_id,
        status=report.status,  # type: ignore[arg-type]
        title=report.title,
        locale=normalize_locale(getattr(report, "locale", None)),
        mode=_normalize_mode(getattr(report, "mode", None)),  # type: ignore[arg-type]
        sources=_normalize_sources(list(report.sources or [])),
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
    customer_id: int | None = None,
    limit: int = 50,
) -> list[Report]:
    stmt = select(Report).order_by(Report.created_at.desc()).limit(min(max(limit, 1), 100))
    if status is not None:
        stmt = stmt.where(Report.status == status)
    if customer_id is not None:
        stmt = stmt.where(Report.customer_id == customer_id)
    return list((await session.execute(stmt)).scalars().all())


async def publish_report(report: Report) -> None:
    await report_hub.publish(
        {
            "type": "report.updated",
            "report": serialize_report(report).model_dump(mode="json"),
        }
    )


async def publish_reports_deleted(entries: list[tuple[str, int | None]]) -> None:
    if not entries:
        return
    by_customer: dict[int | None, list[str]] = {}
    for report_id, customer_id in entries:
        by_customer.setdefault(customer_id, []).append(report_id)
    for customer_id, ids in by_customer.items():
        await report_hub.publish(
            {
                "type": "report.deleted",
                "customer_id": customer_id,
                "ids": list(ids),
            }
        )
