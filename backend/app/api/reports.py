"""Create / list / fetch HTML simulation reports."""

from __future__ import annotations

import logging
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access, effective_customer_id
from app.database.models import PanelSession, Report, Run, UserAccount
from app.database.session import get_session
from app.modules.registry import resolve_report_mode, source_types_for_registry
from app.modules.report_binding import UnknownReportModeError
from app.schemas.domain import (
    JobCreate,
    RecommendationSnapshot,
    ReportBulkDelete,
    ReportBulkDeleteResult,
    ReportCreate,
    ReportGenerateJobRequest,
    ReportOut,
    ReportStatus,
    VerdictCalibrationOut,
    VerdictCalibrationWrite,
)
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.customer_scope import customer_id_for_new_report
from app.services.dd.candidate_runs import (
    get_candidate_run,
)
from app.services.dd.candidate_runs import (
    upsert_report as upsert_dd_candidate_report,
)
from app.services.expertgranskning import SOURCE_TYPE as EXPERTGRANSKNING_SOURCE
from app.services.expertgranskning.sessions import is_expertgranskning_session
from app.services.object_storage import ObjectStorageError
from app.services.panel.result import dd_panel_result_from_stored
from app.services.report import ARTIFACT_ROOT
from app.services.report.bundles import attempt_has_data, find_attempt
from app.services.report.dd_report import render_dd_html_from_artifact
from app.services.report.locale import (
    default_report_title,
    download_filename,
    normalize_locale,
)
from app.services.report.verdict_calibration import (
    get_calibration_row,
    load_recommendation_snapshot,
    serialize_calibration,
    upsert_calibration,
)
from app.services.report_realtime import (
    list_reports as list_report_rows,
)
from app.services.report_realtime import (
    publish_report,
    publish_reports_deleted,
    serialize_report,
)
from app.services.spindoctor_board import clear_spindoctor_widgets
from app.services.spindoctor_chat import clear_spindoctor_messages
from app.services.stored_objects import (
    delete_objects_for_report,
    read_stored_bytes,
    report_html_object,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _serialize(report: Report) -> ReportOut:
    return serialize_report(report)


async def _validate_oasis_source(
    session: AsyncSession,
    src,
    *,
    index: int,
) -> dict:
    run = await session.get(Run, src.run_id)
    if run is None:
        raise HTTPException(status_code=400, detail=f"Run not found: {src.run_id}")
    attempt = find_attempt(
        run.results if isinstance(run.results, dict) else None,
        src.attempt_id or "",
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
    return {
        "type": "oasis",
        "run_id": src.run_id,
        "attempt_id": src.attempt_id,
        "label": f"{run.name} ({index + 1})",
    }


async def _validate_dd_session_source(session: AsyncSession, src) -> dict:
    panel = await session.get(PanelSession, src.session_id)
    if panel is None:
        raise HTTPException(status_code=400, detail=f"Panel session not found: {src.session_id}")
    if panel.protocol != "dd_panel":
        raise HTTPException(status_code=400, detail="Report source must be a dd_panel session")
    if panel.status != "succeeded":
        raise HTTPException(status_code=400, detail="Panel session has not succeeded")
    if not isinstance(panel.result, dict):
        raise HTTPException(status_code=400, detail="Panel session has no result payload")
    result = dd_panel_result_from_stored(panel.result)
    if result.candidate.id != src.candidate_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"candidate_id {src.candidate_id!r} does not match session result "
                f"({result.candidate.id!r})"
            ),
        )
    return {
        "type": "dd_session",
        "session_id": src.session_id,
        "candidate_id": src.candidate_id,
        "label": result.candidate.namn,
    }


async def _validate_expertgranskning_session_source(session: AsyncSession, src) -> dict:
    panel = await session.get(PanelSession, src.session_id)
    if panel is None:
        raise HTTPException(status_code=400, detail=f"Panel session not found: {src.session_id}")
    if not is_expertgranskning_session(panel):
        raise HTTPException(
            status_code=400,
            detail="Report source must be an expertgranskning generic_panel session",
        )
    if panel.status != "succeeded":
        raise HTTPException(status_code=400, detail="Panel session has not succeeded")
    if not isinstance(panel.result, dict):
        raise HTTPException(status_code=400, detail="Panel session has no result payload")
    config = panel.config if isinstance(panel.config, dict) else {}
    return {
        "type": EXPERTGRANSKNING_SOURCE,
        "session_id": src.session_id,
        "label": str(config.get("topic") or "Expertgranskning"),
    }


async def _validate_sources(session: AsyncSession, body: ReportCreate) -> tuple[list[dict], str]:
    source_type = body.sources[0].type
    known = source_types_for_registry()
    if source_type not in known:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown report source type {source_type!r}",
        )
    try:
        mode = resolve_report_mode(source_type, body.mode)
    except (UnknownReportModeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sources: list[dict] = []
    for i, src in enumerate(body.sources):
        if src.type == "dd_session":
            sources.append(await _validate_dd_session_source(session, src))
        elif src.type == "oasis":
            sources.append(await _validate_oasis_source(session, src, index=i))
        elif src.type == EXPERTGRANSKNING_SOURCE:
            sources.append(await _validate_expertgranskning_session_source(session, src))
        else:
            payload = {key: value for key, value in src.model_dump().items() if value is not None}
            payload.setdefault("label", src.type)
            sources.append(payload)
    return sources, mode


async def _reuse_dd_report(
    session: AsyncSession,
    *,
    sources: list[dict],
    body: ReportCreate,
) -> Report | None:
    if not body.sources:
        return None
    src = body.sources[0]
    panel = await session.get(PanelSession, src.session_id)
    if panel is None or panel.campaign_id is None or not src.candidate_id:
        return None
    run = await get_candidate_run(
        session, campaign_id=panel.campaign_id, candidate_id=src.candidate_id
    )
    if run is None or not run.report_id:
        return None
    report = await session.get(Report, run.report_id)
    if report is None or report.mode != "dd":
        return None
    report.status = "pending"
    if (body.title or "").strip():
        report.title = body.title.strip()
    report.locale = normalize_locale(body.locale)
    report.sources = sources
    flag_modified(report, "sources")
    report.html_path = None
    report.slots_path = None
    await delete_objects_for_report(session, report.id)
    report.job_id = None
    report.error = None
    report.created_at = utcnow()
    report.finished_at = None
    report.updated_at = utcnow()
    await session.flush()
    return report


@router.post("", response_model=ReportOut, status_code=202)
async def create_report(
    body: ReportCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ReportOut:
    sources, mode = await _validate_sources(session, body)
    locale = normalize_locale(body.locale)
    ab_source = False
    if mode == "quick" and len(sources) == 1:
        run = await session.get(Run, sources[0]["run_id"])
        ab_source = run is not None and bool(run.branch)
    if (body.title or "").strip():
        title = body.title.strip()
    elif mode in {"dd", "expertgranskning"} and sources:
        title = str(sources[0]["label"])
    else:
        source_label = sources[0]["label"].rsplit(" (", 1)[0] if sources else ""
        title = default_report_title(
            locale=locale,
            ab_source=ab_source,
            source_label=source_label,
            n_sources=len(sources),
        )

    reused = await _reuse_dd_report(session, sources=sources, body=body) if mode == "dd" else None
    if reused is not None:
        assert_kund_access(user, reused.customer_id)
        report = reused
        report_id = report.id
    else:
        report_id = f"rpt_{secrets.token_hex(8)}"
        customer_id = await customer_id_for_new_report(session, body, sources=sources, mode=mode)
        assert_kund_access(user, customer_id)
        report = Report(
            id=report_id,
            customer_id=customer_id,
            status="pending",
            title=title,
            locale=locale,
            mode=mode,
            sources=sources,
            html_path=None,
            slots_path=None,
            job_id=None,
            error=None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(report)
        await session.flush()
        if mode == "dd" and body.sources:
            src = body.sources[0]
            panel = await session.get(PanelSession, src.session_id)
            if panel is not None and panel.campaign_id is not None and src.candidate_id:
                await upsert_dd_candidate_report(
                    session,
                    campaign_id=panel.campaign_id,
                    candidate_id=src.candidate_id,
                    report_id=report_id,
                )
    await session.commit()
    await session.refresh(report)
    if reused is not None:
        await clear_spindoctor_messages(session, report.id)
        await clear_spindoctor_widgets(session, report.id)

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
    customer_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[ReportOut]:
    customer_id = effective_customer_id(user, customer_id)
    rows = await list_report_rows(
        session, status=status, customer_id=customer_id, limit=limit
    )
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
    deleted_entries: list[tuple[str, int | None]] = []
    for report_id in unique:
        report = await session.get(Report, report_id)
        if report is None:
            continue
        deleted_entries.append((report_id, report.customer_id))
        try:
            await delete_objects_for_report(session, report_id)
        except ObjectStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        await session.delete(report)
        deleted.append(report_id)
    if deleted:
        await session.commit()
        for report_id in deleted:
            _remove_report_artifacts(report_id)
        await publish_reports_deleted(deleted_entries)
    return deleted


@router.post("/bulk-delete", response_model=ReportBulkDeleteResult)
async def bulk_delete_reports(
    body: ReportBulkDelete,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ReportBulkDeleteResult:
    for report_id in dict.fromkeys(body.ids):
        report = await session.get(Report, report_id)
        if report is None:
            continue
        assert_kund_access(user, report.customer_id)
    deleted_ids = await _delete_reports_by_ids(session, body.ids)
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="No matching reports")
    return ReportBulkDeleteResult(deleted_ids=deleted_ids)


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ReportOut:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    assert_kund_access(user, report.customer_id)
    return _serialize(report)


def _require_succeeded_report(report: Report) -> None:
    if report.status != "succeeded":
        raise HTTPException(status_code=404, detail="Report not ready")


def _recommendation_out(report_id: str) -> RecommendationSnapshot | None:
    block = load_recommendation_snapshot(report_id)
    if block is None:
        return None
    return RecommendationSnapshot(
        score=int(block["score"]),
        action=str(block["action"]),
        recommended_arm=block.get("recommended_arm") if block.get("recommended_arm") else None,
        verdict_key=str(block.get("verdict_key") or ""),
    )


@router.get("/{report_id}/verdict-calibration", response_model=VerdictCalibrationOut)
async def get_verdict_calibration(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> VerdictCalibrationOut:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    assert_kund_access(user, report.customer_id)
    _require_succeeded_report(report)
    recommendation = _recommendation_out(report_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Report recommendation snapshot missing")
    row = await get_calibration_row(session, report_id)
    payload = serialize_calibration(report, row, recommendation.model_dump())
    return VerdictCalibrationOut(**payload)


@router.post("/{report_id}/verdict-calibration", response_model=VerdictCalibrationOut)
async def post_verdict_calibration(
    report_id: str,
    body: VerdictCalibrationWrite,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> VerdictCalibrationOut:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    assert_kund_access(user, report.customer_id)
    _require_succeeded_report(report)
    recommendation = _recommendation_out(report_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Report recommendation snapshot missing")
    row = await upsert_calibration(
        session,
        report_id=report_id,
        matches=body.matches,
        note=body.note,
    )
    payload = serialize_calibration(report, row, recommendation.model_dump())
    return VerdictCalibrationOut(**payload)


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    assert_kund_access(user, report.customer_id)
    deleted = await _delete_reports_by_ids(session, [report_id])
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")
    return Response(status_code=204)


@router.get("/{report_id}/html", response_class=HTMLResponse)
async def get_report_html(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> HTMLResponse:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    assert_kund_access(user, report.customer_id)
    if report.status != "succeeded":
        raise HTTPException(status_code=404, detail="Report HTML not ready")
    filename = download_filename(normalize_locale(getattr(report, "locale", None)))
    stored = await report_html_object(session, report_id)
    if stored is not None:
        try:
            data, _content_type = await read_stored_bytes(stored)
        except ObjectStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return HTMLResponse(
            content=data.decode("utf-8"),
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    if getattr(report, "mode", None) == "dd":
        fresh = render_dd_html_from_artifact(
            Path(ARTIFACT_ROOT) / report_id,
            title=report.title,
            locale=getattr(report, "locale", None) or "sv",
        )
        if fresh:
            return HTMLResponse(
                content=fresh,
                headers={"Content-Disposition": f'inline; filename="{filename}"'},
            )
    if not report.html_path:
        raise HTTPException(status_code=404, detail="Report HTML not ready")
    path = Path(report.html_path)
    if not path.is_file():
        alt = Path(ARTIFACT_ROOT) / report_id / "report.html"
        if alt.is_file():
            path = alt
        else:
            raise HTTPException(status_code=404, detail="Report file missing")
    return HTMLResponse(
        content=path.read_text(encoding="utf-8"),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
