"""Spinndoktor helpers for DD reports (report.dd.json)."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.modules.manifest import SpindoctorSource
from app.services.dd.sub_questions import SubQuestionRef
from app.services.report import ARTIFACT_ROOT
from app.services.report.locale import ReportLocale


class _SubQuestionLike(Protocol):
    id: str
    label: str


def load_dd_report_json(report_id: str) -> dict[str, Any] | None:
    path = Path(ARTIFACT_ROOT) / report_id / "report.dd.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sub_questions_from_dd_doc(dd_doc: dict[str, Any]) -> list[SubQuestionRef]:
    """Derive ordered sub-question refs from scores/unanswered already in the doc."""
    ordered: list[SubQuestionRef] = []
    seen: set[str] = set()
    for key in ("scores", "unanswered", "dissensus"):
        for row in dd_doc.get(key) or []:
            if not isinstance(row, dict):
                continue
            sq_id = str(row.get("sub_question_id") or "").strip()
            label = str(row.get("sub_question_label") or sq_id).strip()
            if not sq_id or sq_id in seen:
                continue
            seen.add(sq_id)
            ordered.append(SubQuestionRef(id=sq_id, label=label or sq_id))
    return ordered


def average_scores_by_sub_question(
    dd_doc: dict[str, Any],
    sub_questions: Sequence[_SubQuestionLike],
) -> list[dict[str, float | str]]:
    """Mean expert score (1–10) per sub-question, ordered like ``sub_questions``."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for row in dd_doc.get("scores") or []:
        if not isinstance(row, dict):
            continue
        sq_id = str(row.get("sub_question_id") or "").strip()
        try:
            score = int(row.get("score"))
        except (TypeError, ValueError):
            continue
        if sq_id:
            buckets[sq_id].append(score)
    out: list[dict[str, float | str]] = []
    for sq in sub_questions:
        values = buckets.get(sq.id, [])
        if not values:
            continue
        out.append(
            {
                "sub_question_id": sq.id,
                "label": sq.label,
                "value": round(sum(values) / len(values), 1),
            }
        )
    return out


def _format_candidate(candidate: dict[str, Any], *, locale: ReportLocale) -> list[str]:
    if locale == "en":
        labels = [
            ("Company", "namn"),
            ("Org. no.", "organisationsnummer"),
            ("Age (years)", "alder_ar"),
            ("Region", "omrade"),
            ("Result", "resultat"),
            ("Revenue (SEK)", "omsattning_sek"),
            ("Employees", "anstallda"),
        ]
    else:
        labels = [
            ("Bolag", "namn"),
            ("Org.nr", "organisationsnummer"),
            ("Ålder (år)", "alder_ar"),
            ("Område", "omrade"),
            ("Resultat", "resultat"),
            ("Omsättning (SEK)", "omsattning_sek"),
            ("Anställda", "anstallda"),
        ]
    lines: list[str] = []
    for label, key in labels:
        value = candidate.get(key)
        if value is None or value == "":
            display = "—"
        else:
            display = str(value)
        lines.append(f"{label}: {display}")
    desc = str(candidate.get("beskrivning") or "").strip()
    if desc:
        lines.append(desc)
    return lines


async def load_dd_spindoctor_source(
    session: AsyncSession, report: Report
) -> SpindoctorSource:
    """Load report.dd.json into a uniform Spinndoktor source. session unused (file artifact)."""
    del session
    dd_doc = load_dd_report_json(report.id)
    if dd_doc is None:
        raise ValueError(f"report.dd.json not found for {report.id!r}")
    return SpindoctorSource(report=report, payload=dd_doc, bundles=[])


def build_dd_spindoctor_context_from_source(
    source: SpindoctorSource, *, locale: str, title: str
) -> str:
    return build_dd_spindoctor_context_block(source.payload, locale=locale, title=title)


def build_dd_spindoctor_context_block(
    dd_doc: dict[str, Any],
    *,
    locale: ReportLocale,
    title: str,
) -> str:
    candidate = dd_doc.get("candidate") if isinstance(dd_doc.get("candidate"), dict) else {}
    summary = str(dd_doc.get("summary") or "").strip()
    dissensus = dd_doc.get("dissensus") if isinstance(dd_doc.get("dissensus"), list) else []
    unanswered = dd_doc.get("unanswered") if isinstance(dd_doc.get("unanswered"), list) else []

    if locale == "en":
        header = f"DD report: {title}"
        parts = [header, ""]
        parts.append("## Candidate")
    else:
        header = f"DD-rapport: {title}"
        parts = [header, ""]
        parts.append("## Kandidat")

    parts.extend(_format_candidate(candidate, locale=locale))
    parts.append("")
    parts.append("## Summary" if locale == "en" else "## Sammanfattning")
    parts.append(summary or ("—" if locale == "en" else "—"))

    parts.append("")
    parts.append("## Expert scores (1–10)" if locale == "en" else "## Expertpoäng (1–10)")
    for row in dd_doc.get("scores") or []:
        if not isinstance(row, dict):
            continue
        parts.append(
            f"- {row.get('expert_label')} · {row.get('sub_question_label')}: "
            f"{row.get('score')}/10 — {row.get('motivation')}"
        )

    if dissensus:
        parts.append("")
        parts.append("## Dissensus" if locale == "en" else "## Dissensus")
        for note in dissensus:
            if not isinstance(note, dict):
                continue
            parts.append(
                f"- {note.get('sub_question_label')}: spread {note.get('spread')} "
                f"({note.get('min_score')}–{note.get('max_score')})"
            )

    if unanswered:
        parts.append("")
        parts.append("## Unanswered" if locale == "en" else "## Obesvarade delfrågor")
        for note in unanswered:
            if not isinstance(note, dict):
                continue
            parts.append(
                f"- {note.get('sub_question_label')}: {note.get('moderator_note')}"
            )

    averages = average_scores_by_sub_question(dd_doc, sub_questions_from_dd_doc(dd_doc))
    if averages:
        parts.append("")
        parts.append(
            "## Mean score per sub-question (for radar charts)"
            if locale == "en"
            else "## Medelpoäng per delfråga (för radardiagram)"
        )
        for row in averages:
            parts.append(f"- {row['label']}: {row['value']}/10")

    if locale == "en":
        parts.append("")
        parts.append(
            "Report section refs (append [[ref:id]] when pointing the user to a section): "
            "sammanfattning, kandidat, delfragor, poangmatris, kallbilaga, obesvarade. "
            "Sub-questions also have ids like delfraga-finansiell_halsa."
        )
        parts.append(
            "Use get_report_dd for full structured data. For scoring charts on this candidate, "
            "call render_chart with chart_type radar (0–10 scale, one axis per sub-question)."
        )
    else:
        parts.append("")
        parts.append(
            "Rapportsektioner (lägg [[ref:id]] sist när du pekar läsaren till en del): "
            "sammanfattning, kandidat, delfragor, poangmatris, kallbilaga, obesvarade. "
            "Delfrågor har också id som delfraga-finansiell_halsa."
        )
        parts.append(
            "Använd get_report_dd för full strukturerad data. För poängdiagram för den här "
            "kandidaten: render_chart med chart_type radar (skala 0–10, en axel per delfråga)."
        )
    return "\n".join(parts)
