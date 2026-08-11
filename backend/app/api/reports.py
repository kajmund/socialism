"""Create / list / fetch HTML simulation reports."""

from __future__ import annotations

import logging
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report, Run
from app.database.session import get_session
from app.schemas.domain import (
    JobCreate,
    ReportBulkDelete,
    ReportBulkDeleteResult,
    ReportCreate,
    ReportGenerateJobRequest,
    ReportOut,
    ReportStatus,
)
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.report import ARTIFACT_ROOT
from app.services.report.bundles import attempt_has_data, find_attempt
from app.services.report.locale import (
    default_report_title,
    download_filename,
    normalize_locale,
)
from app.services.report_realtime import (
    list_reports as list_report_rows,
    publish_report,
    publish_reports_deleted,
    serialize_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _serialize(report: Report) -> ReportOut:
    return serialize_report(report)


async def _validate_sources(session: AsyncSession, body: ReportCreate) -> list[dict]:
    sources: list[dict] = []
    for i, src in enumerate(body.sources):
        run = await session.get(Run, src.run_id)
        if run is None:
            raise HTTPException(status_code=400, detail=f"Run not found: {src.run_id}")
        attempt = find_attempt(
            run.results if isinstance(run.results, dict) else None,
            src.attempt_id,
        )
        if attempt is None:
            raise HTTPException(
                status_code=400,
                detail=f"Attempt not found: {src.attempt_id} on run {src.run_id}",
            )
        if not attempt_has_data(attempt):
            raise HTTPException(
                status_code=400,
                detail=f"Attempt {src.attempt_id} has no simulation data",
            )
        sources.append(
            {
                "run_id": src.run_id,
                "attempt_id": src.attempt_id,
                "label": f"{run.name} ({i + 1})",
            }
        )
    return sources


@router.post("", response_model=ReportOut, status_code=202)
async def create_report(
    body: ReportCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> ReportOut:
    sources = await _validate_sources(session, body)
    report_id = f"rpt_{secrets.token_hex(8)}"
    locale = normalize_locale(body.locale)
    ab_source = False
    if len(sources) == 1:
        run = await session.get(Run, sources[0]["run_id"])
        ab_source = run is not None and bool(run.branch)
    if (body.title or "").strip():
        title = body.title.strip()
    else:
        source_label = sources[0]["label"].rsplit(" (", 1)[0] if sources else ""
        title = default_report_title(
            locale=locale,
            ab_source=ab_source,
            source_label=source_label,
            n_sources=len(sources),
        )

    report = Report(
        id=report_id,
        status="pending",
        title=title,
        locale=locale,
        mode="quick",
        sources=sources,
        html_path=None,
        slots_path=None,
        job_id=None,
        error=None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)

    try:
        job = await jobs_service.create_job(
            session,
            JobCreate(
                kind="report_generate",
                label=title,
                request=ReportGenerateJobRequest(report_id=report_id).model_dump(),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=500, detail="Report disappeared")
    report.job_id = job.id
    report.updated_at = utcnow()
    await session.commit()
    await session.refresh(report)
    await publish_report(report)

    jobs_service.enqueue_job(job.id)
    response.status_code = 202
    return _serialize(report)


@router.get("", response_model=list[ReportOut])
async def list_reports(
    status: ReportStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[ReportOut]:
    rows = await list_report_rows(session, status=status, limit=limit)
    return [_serialize(r) for r in rows]


def _remove_report_artifacts(report_id: str) -> None:
    path = Path(ARTIFACT_ROOT) / report_id
    if path.is_dir():
        shutil.rmtree(path)
        logger.info("Removed report artifacts at %s", path)


async def _delete_reports_by_ids(
    session: AsyncSession,
    ids: list[str],
) -> list[str]:
    """Delete existing reports by id. Returns ids that were removed."""
    unique = list(dict.fromkeys(ids))
    deleted: list[str] = []
    for report_id in unique:
        report = await session.get(Report, report_id)
        if report is None:
            continue
        await session.delete(report)
        deleted.append(report_id)
    if deleted:
        await session.commit()
        for report_id in deleted:
            _remove_report_artifacts(report_id)
        await publish_reports_deleted(deleted)
    return deleted


@router.post("/bulk-delete", response_model=ReportBulkDeleteResult)
async def bulk_delete_reports(
    body: ReportBulkDelete,
    session: AsyncSession = Depends(get_session),
) -> ReportBulkDeleteResult:
    deleted_ids = await _delete_reports_by_ids(session, body.ids)
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="No matching reports")
    return ReportBulkDeleteResult(deleted_ids=deleted_ids)


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> ReportOut:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _serialize(report)


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    deleted = await _delete_reports_by_ids(session, [report_id])
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")
    return Response(status_code=204)


@router.get("/{report_id}/html", response_class=HTMLResponse)
async def get_report_html(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "succeeded" or not report.html_path:
        raise HTTPException(status_code=404, detail="Report HTML not ready")
    path = Path(report.html_path)
    if not path.is_file():
        alt = Path(ARTIFACT_ROOT) / report_id / "report.html"
        if alt.is_file():
            path = alt
        else:
            raise HTTPException(status_code=404, detail="Report file missing")
    filename = download_filename(normalize_locale(getattr(report, "locale", None)))
    return HTMLResponse(
        content=path.read_text(encoding="utf-8"),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
