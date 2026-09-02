"""Spinndoktor helpers for expertgranskning reports (free-text document + panel)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.modules.manifest import SpindoctorSource
from app.services.expertgranskning.report_html import load_expertgranskning_report_json
from app.services.report.locale import ReportLocale, normalize_locale


async def load_expertgranskning_spindoctor_source(
    session: AsyncSession, report: Report
) -> SpindoctorSource:
    del session
    payload = load_expertgranskning_report_json(report.id)
    if payload is None:
        raise ValueError(f"report.expertgranskning.json not found for {report.id!r}")
    return SpindoctorSource(report=report, payload=payload, bundles=[])


def _transcript_lines(transcript: list[Any]) -> list[str]:
    lines: list[str] = []
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("phase") or "") == "scratchpad":
            continue
        speaker = str(turn.get("speaker") or "").strip()
        content = str(turn.get("content") or "").strip()
        if not speaker and not content:
            continue
        lines.append(f"{speaker}: {content}" if speaker else content)
    return lines


def build_expertgranskning_spindoctor_context_from_source(
    source: SpindoctorSource, *, locale: str, title: str
) -> str:
    loc: ReportLocale = normalize_locale(locale)
    payload = source.payload if isinstance(source.payload, dict) else {}
    document_text = str(payload.get("document_text") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    transcript = payload.get("transcript") if isinstance(payload.get("transcript"), list) else []

    if loc == "en":
        parts = [
            f"Expert review report: {title}",
            "",
            "## Document",
            document_text or "—",
            "",
            "## Summary",
            summary or "—",
        ]
        turns = _transcript_lines(transcript)
        if turns:
            parts.extend(["", "## Panel transcript", *turns])
        return "\n".join(parts)

    parts = [
        f"Expertgranskning-rapport: {title}",
        "",
        "## Dokument",
        document_text or "—",
        "",
        "## Sammanfattning",
        summary or "—",
    ]
    turns = _transcript_lines(transcript)
    if turns:
        parts.extend(["", "## Panelens turer", *turns])
    return "\n".join(parts)
