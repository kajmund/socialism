"""REST endpoints for Spinndoktor chat history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.database.session import get_session
from app.schemas.domain import SpindoctorMessageOut
from app.services.spindoctor_chat import (
    clear_spindoctor_messages,
    list_spindoctor_messages,
)

router = APIRouter(prefix="/spindoctor", tags=["spindoctor"])


async def _require_succeeded_report(session: AsyncSession, report_id: str) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "succeeded":
        raise HTTPException(status_code=400, detail="Report is not ready for Spinndoktor")
    return report


@router.get("/messages", response_model=list[SpindoctorMessageOut])
async def get_spindoctor_messages(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[SpindoctorMessageOut]:
    await _require_succeeded_report(session, report_id)
    return await list_spindoctor_messages(session, report_id)


@router.delete("/messages", status_code=204)
async def delete_spindoctor_messages(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    await _require_succeeded_report(session, report_id)
    await clear_spindoctor_messages(session, report_id)
