"""Operator verdict calibration against report recommendation snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report, ReportVerdictCalibration
from app.serializers import utcnow
from app.services.report import ARTIFACT_ROOT


def load_recommendation_snapshot(report_id: str) -> dict[str, Any] | None:
    path = Path(ARTIFACT_ROOT) / report_id / "report.ssr.json"
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    block = doc.get("recommendation")
    if not isinstance(block, dict):
        return None
    if "action" not in block or "score" not in block:
        return None
    return block


async def get_calibration_row(
    session: AsyncSession,
    report_id: str,
) -> ReportVerdictCalibration | None:
    return await session.get(ReportVerdictCalibration, report_id)


async def upsert_calibration(
    session: AsyncSession,
    *,
    report_id: str,
    matches: bool,
    note: str | None,
) -> ReportVerdictCalibration:
    row = await session.get(ReportVerdictCalibration, report_id)
    note_text = note.strip() if note and note.strip() else None
    now = utcnow()
    if row is None:
        row = ReportVerdictCalibration(
            report_id=report_id,
            matches=matches,
            note=note_text,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.matches = matches
        row.note = note_text
        row.updated_at = now
    await session.commit()
    await session.refresh(row)
    return row


def serialize_calibration(
    report: Report,
    row: ReportVerdictCalibration | None,
    recommendation: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "report_id": report.id,
        "matches": row.matches if row is not None else None,
        "note": row.note if row is not None else None,
        "recommendation": recommendation,
        "updated_at": row.updated_at.isoformat() if row is not None else None,
    }
