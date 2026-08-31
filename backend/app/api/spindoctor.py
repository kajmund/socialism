"""REST endpoints for Spinndoktor chat history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access
from app.database.models import Report, UserAccount
from app.database.session import get_session
from app.schemas.domain import (
    SpindoctorMessageOut,
    SpindoctorWidgetOut,
    SpindoctorWidgetPositionIn,
)
from app.services.spindoctor_board import (
    clear_spindoctor_widgets,
    delete_spindoctor_widget,
    list_spindoctor_widgets,
    update_spindoctor_widget_position,
)
from app.services.spindoctor_chat import (
    clear_spindoctor_messages,
    list_spindoctor_messages,
)

router = APIRouter(prefix="/spindoctor", tags=["spindoctor"])


async def _require_succeeded_report(
    session: AsyncSession,
    report_id: str,
    user: UserAccount,
) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    assert_kund_access(user, report.customer_id)
    if report.status != "succeeded":
        raise HTTPException(status_code=400, detail="Report is not ready for Spinndoktor")
    return report


@router.get("/messages", response_model=list[SpindoctorMessageOut])
async def get_spindoctor_messages(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[SpindoctorMessageOut]:
    await _require_succeeded_report(session, report_id, user)
    return await list_spindoctor_messages(session, report_id)


@router.delete("/messages", status_code=204)
async def delete_spindoctor_messages(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    await _require_succeeded_report(session, report_id, user)
    await clear_spindoctor_messages(session, report_id)


@router.get("/widgets", response_model=list[SpindoctorWidgetOut])
async def get_spindoctor_widgets(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[SpindoctorWidgetOut]:
    await _require_succeeded_report(session, report_id, user)
    return await list_spindoctor_widgets(session, report_id)


@router.patch("/widgets/{widget_id}", response_model=SpindoctorWidgetOut)
async def patch_spindoctor_widget(
    widget_id: str,
    body: SpindoctorWidgetPositionIn,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> SpindoctorWidgetOut:
    await _require_succeeded_report(session, body.report_id, user)
    try:
        return await update_spindoctor_widget_position(
            session,
            body.report_id,
            widget_id,
            pos_x=body.pos_x,
            pos_y=body.pos_y,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/widgets/{widget_id}", status_code=204)
async def remove_spindoctor_widget(
    widget_id: str,
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    await _require_succeeded_report(session, report_id, user)
    try:
        await delete_spindoctor_widget(session, report_id, widget_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/widgets", status_code=204)
async def delete_spindoctor_widgets(
    report_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    await _require_succeeded_report(session, report_id, user)
    await clear_spindoctor_widgets(session, report_id)
