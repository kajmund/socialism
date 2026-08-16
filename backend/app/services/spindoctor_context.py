"""Build Spinndoktor system context from report artifacts and run data."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.services.report import ARTIFACT_ROOT
from app.services.report.bundles import RunBundle, build_bundles
from app.services.report.classify import TONE_LABELS
from app.services.report.locale import display_style_label, normalize_locale
from app.services.report.metrics import compute_report_metrics, pct
from app.services.report.persona_bio import PRIMARY_SEGMENT_KEYS
from app.services.report.quick import decide_verdict
from app.services.report.thresholds import (
    ReportThresholds,
    default_report_thresholds,
    normalize_report_thresholds,
)
from app.services.report.verdict_calibration import load_recommendation_snapshot
from app.services.ssr import STYLE_LABELS


def _load_ssr_json(report_id: str) -> dict[str, Any] | None:
    path = Path(ARTIFACT_ROOT) / report_id / "report.ssr.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _age_band(age: int | str) -> str:
    try:
        n = int(age)
    except (TypeError, ValueError):
        return "okänd"
    if n < 30:
        return "ung"
    if n < 55:
        return "medel"
    return "äldre"


def _population_lines(bundles: list[RunBundle], *, locale: str) -> list[str]:
    seen: set[str] = set()
    personas: list[dict[str, Any]] = []
    for bundle in bundles:
        for row in bundle.personas:
            pid = str(row.get("persona_id") or row.get("name") or "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            personas.append(row)
    if not personas:
        return ["Ingen populationsdata tillgänglig."]

    ages = Counter(_age_band(p.get("age", "")) for p in personas)
    occs = Counter(
        str((p.get("bio") or {}).get("yrke") or p.get("occ") or "").strip() or "—"
        for p in personas
    )
    leans = Counter(
        str((p.get("bio") or {}).get("lutning") or "").strip() or "—"
        for p in personas
    )
    districts = Counter(str(p.get("district") or "—").strip() or "—" for p in personas)

    lines = [f"Antal simulerade medborgare: {len(personas)}"]
    if locale == "en":
        lines[0] = f"Simulated citizens: {len(personas)}"

    def _fmt(counter: Counter[str], label_sv: str, label_en: str) -> str:
        total = sum(counter.values()) or 1
        items = counter.most_common(8)
        bits = [f"{k} {v / total:.0%}" for k, v in items if k and k != "—"]
        if not bits:
            return ""
        title = label_en if locale == "en" else label_sv
        return f"{title}: " + ", ".join(bits)

    for block in (
        _fmt(ages, "Ålder", "Age"),
        _fmt(occs, "Yrken", "Occupations"),
        _fmt(leans, "Politisk lutning", "Political leaning"),
        _fmt(districts, "Distrikt/ort", "District/area"),
    ):
        if block:
            lines.append(block)
    return lines


def _engagement_plain(metrics) -> str:
    m = metrics.aggregate
    total = max(1, m.agent_count)
    zero = m.zero_like_agents
    if zero >= total * 0.5:
        return (
            f"Engagemanget är koncentrerat: {zero} av {total} deltagare gav inga likes alls "
            f"({pct(zero / total)})."
        )
    if m.gini >= 0.65:
        return (
            f"Engagemanget är ojämnt fördelat — få röster dominerar debatten "
            f"({m.top_agents} toppengagerade av {total})."
        )
    return (
        f"Engagemanget är spritt över populationen "
        f"({m.top_agents + m.mid_agents} av {total} hade minst någon like)."
    )


def _thresholds_from_ssr_doc(ssr_doc: dict[str, Any] | None) -> ReportThresholds:
    if not ssr_doc:
        return default_report_thresholds()
    raw = ssr_doc.get("report_thresholds")
    if not isinstance(raw, dict):
        return default_report_thresholds()
    return normalize_report_thresholds(raw)


def _confidence_notes(
    metrics,
    bundles: list[RunBundle],
    *,
    locale: str,
    thresholds: ReportThresholds,
) -> list[str]:
    """Plain-language signal strength — maps to report diff bands, not CSS badges."""
    verdict = decide_verdict(metrics, bundles, locale=locale, thresholds=thresholds)
    notes: list[str] = []
    if verdict.threshold_note:
        notes.append(verdict.threshold_note)
    if locale == "en":
        notes.append(
            "Treat 'clear difference' findings as stronger than 'weak signal' or "
            "'within noise'. Segment rows with very few rated texts are uncertain."
        )
    else:
        notes.append(
            "Tolka «tydlig skillnad» som starkare underlag än «svag signal» eller "
            "«inom brus». Segment med väldigt få analyserade texter är osäkra."
        )
    return notes


def _tone_style_topics(
    ssr_doc: dict[str, Any] | None,
    metrics,
    *,
    locale: str,
) -> list[str]:
    lines: list[str] = []
    if ssr_doc:
        for bundle in ssr_doc.get("bundles") or []:
            if not isinstance(bundle, dict):
                continue
            label = str(bundle.get("label") or "")
            tone = bundle.get("tone_shares") or {}
            if isinstance(tone, dict) and tone:
                top = max(tone.items(), key=lambda x: float(x[1] or 0))
                lines.append(
                    f"{label}: dominerande ton {top[0]} ({pct(float(top[1]))})"
                    if locale != "en"
                    else f"{label}: dominant tone {top[0]} ({pct(float(top[1]))})"
                )
            styles = bundle.get("style_shares") or []
            if isinstance(styles, list) and styles:
                ranked = sorted(
                    (
                        (str(row.get("style") or ""), float(row.get("share") or 0))
                        for row in styles
                        if isinstance(row, dict)
                    ),
                    key=lambda x: x[1],
                    reverse=True,
                )
                if ranked and ranked[0][1] > 0:
                    best = ranked[0]
                    shown = display_style_label(best[0], locale=locale)
                    lines.append(
                        f"{label}: starkaste budskapsstil {shown} ({pct(best[1])})"
                        if locale != "en"
                        else f"{label}: strongest message style {shown} ({pct(best[1])})"
                    )
    m = metrics.aggregate
    if m.topic_shares:
        top_topic = max(m.topic_shares.items(), key=lambda x: x[1])
        lines.append(
            f"Dominerande ämne i flödet: {top_topic[0]} ({pct(top_topic[1])})"
            if locale != "en"
            else f"Dominant topic in the feed: {top_topic[0]} ({pct(top_topic[1])})"
        )
    if m.tone_shares and any(v > 0 for v in m.tone_shares.values()):
        ordered = sorted(m.tone_shares.items(), key=lambda x: x[1], reverse=True)
        bits = ", ".join(f"{k} {pct(v)}" for k, v in ordered[:3] if v > 0)
        if bits:
            lines.append(
                f"Tonfördelning (agg): {bits}"
                if locale != "en"
                else f"Tone mix (agg): {bits}"
            )
    return lines


def _leaders_plain(metrics, *, locale: str) -> list[str]:
    actors = metrics.aggregate.top_actors[:3]
    if not actors:
        return []
    lines = []
    for actor in actors:
        name = str(actor.get("name") or "—")
        likes = actor.get("likes_total", 0)
        sample = str(actor.get("sample") or "").strip()
        line = f"{name}: {likes} likes totalt"
        if locale == "en":
            line = f"{name}: {likes} total likes"
        if sample:
            line += f' — exempel: "{sample[:120]}"'
        lines.append(line)
    return lines


def _section_ref_catalog(*, locale: str) -> str:
    if locale == "en":
        return (
            "Report section refs (append [[ref:id]] at end of reply when pointing the user "
            "to a section): mottagande (engagement), budskapsstilar (message styles), "
            "amneskontroll (topics), opinionsledare (opinion voices), valjargrupper "
            "(target groups), rekommendation (recommendation), appendix (technical notes)."
        )
    return (
        "Rapportsektioner (lägg [[ref:id]] sist i svaret när du pekar läsaren till en del): "
        "mottagande (engagemang), budskapsstilar, amneskontroll (ämnen), opinionsledare, "
        "valjargrupper, rekommendation, appendix (tekniska noter)."
    )


async def build_spindoctor_context(
    session: AsyncSession,
    *,
    report_id: str,
) -> tuple[Report, str]:
    """Return report row and formatted context block for the system prompt."""
    report = await session.get(Report, report_id)
    if report is None:
        raise ValueError(f"Report {report_id!r} not found")
    if report.status != "succeeded":
        raise ValueError(f"Report {report_id!r} is not ready (status={report.status})")

    locale = normalize_locale(report.locale or "sv")
    sources = report.sources if isinstance(report.sources, list) else []
    if not sources:
        raise ValueError(f"Report {report_id!r} has no sources")

    bundles = await build_bundles(session, sources)
    metrics = compute_report_metrics(bundles)
    ssr_doc = _load_ssr_json(report_id)
    report_thresholds = _thresholds_from_ssr_doc(ssr_doc)
    recommendation = load_recommendation_snapshot(report_id)

    if locale == "en":
        header = f"Report: {report.title or report_id}"
        run_line = f"Sources: {len(bundles)} bundle(s) from {len(sources)} run attempt(s)."
    else:
        header = f"Rapport: {report.title or report_id}"
        run_line = f"Källor: {len(bundles)} bundle(s) från {len(sources)} körningsförsök."

    parts = [header, run_line, ""]
    parts.append("## Population" if locale == "en" else "## Population")
    parts.extend(_population_lines(bundles, locale=locale))
    parts.append("")
    parts.append("## Resultat — engagemang och ton" if locale == "en" else "## Resultat — engagemang och ton")
    parts.append(_engagement_plain(metrics))
    parts.extend(_tone_style_topics(ssr_doc, metrics, locale=locale))
    leaders = _leaders_plain(metrics, locale=locale)
    if leaders:
        parts.append("")
        parts.append("## Opinionsledare (topp 3)" if locale == "en" else "## Opinionsledare (topp 3)")
        parts.extend(leaders)
    if recommendation:
        parts.append("")
        parts.append("## Rekommendation (från rapporten)" if locale == "en" else "## Rekommendation (från rapporten)")
        parts.append(
            f"Handling: {recommendation.get('action')} · "
            f"Score: {recommendation.get('score')}/100"
        )
        if recommendation.get("recommended_arm"):
            parts.append(f"Version: {recommendation.get('recommended_arm')}")
    parts.append("")
    parts.append("## Signalsstyrka" if locale == "en" else "## Signalsstyrka")
    parts.extend(
        _confidence_notes(metrics, bundles, locale=locale, thresholds=report_thresholds)
    )
    parts.append("")
    parts.append(_section_ref_catalog(locale=locale))
    parts.append("")
    parts.append(
        "Primary segment keys used in the report: "
        + ", ".join(PRIMARY_SEGMENT_KEYS)
        if locale == "en"
        else "Primära segment i rapporten: " + ", ".join(PRIMARY_SEGMENT_KEYS)
    )
    parts.append(
        f"Tone labels: {', '.join(TONE_LABELS)} · Style labels: {', '.join(STYLE_LABELS)}"
    )
    return report, "\n".join(parts)
