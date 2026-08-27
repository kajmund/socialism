"""Template-based DD report: render DdPanelResult from panel session."""

from __future__ import annotations

import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from app.services.dd.schemas import DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge, SourceKind
from app.services.dd.sub_questions import DD_SUB_QUESTIONS
from app.services.panel.schemas import DdDissensusNote, DdExpertScore, DdPanelResult
from app.services.report.locale import ReportLocale, normalize_locale
from app.services.report.render import REPORT_FONTS_HREF, inject_report_theme

_SOURCE_BADGE_CLASS: dict[SourceKind, str] = {
    "okf": "confirmed",
    "web": "web",
    "llm": "single",
}


def _source_badge_html(source: SourceBadge) -> str:
    css = _SOURCE_BADGE_CLASS.get(source.kind, "single")
    title = escape(source.detail) if source.detail else ""
    title_attr = f' title="{title}"' if title else ""
    return (
        f'<span class="badge {css}"{title_attr}>'
        f"{escape(source.label)}</span>"
    )


def _format_sek(value: int | None, *, locale: ReportLocale) -> str:
    if value is None:
        return "—"
    text = f"{value:,}".replace(",", " ")
    return f"{text} SEK" if locale == "sv" else f"SEK {text}"


def _format_resultat(value: str, *, locale: ReportLocale) -> str:
    mapping_sv = {"vinst": "Vinst", "förlust": "Förlust", "oavsett": "Oavsett"}
    mapping_en = {"vinst": "Profit", "förlust": "Loss", "oavsett": "Any"}
    mapping = mapping_en if locale == "en" else mapping_sv
    return mapping.get(value, value)


def _candidate_meta_rows(candidate: DdCandidateCompany, *, locale: ReportLocale) -> list[tuple[str, str]]:
    if locale == "en":
        return [
            ("Company", candidate.namn),
            ("Org. no.", candidate.organisationsnummer),
            ("Age (years)", str(candidate.alder_ar)),
            ("Region", candidate.omrade or "—"),
            ("Result", _format_resultat(candidate.resultat, locale=locale)),
            ("Revenue", _format_sek(candidate.omsattning_sek, locale=locale)),
            ("Employees", str(candidate.anstallda) if candidate.anstallda is not None else "—"),
        ]
    return [
        ("Bolag", candidate.namn),
        ("Org.nr", candidate.organisationsnummer),
        ("Ålder (år)", str(candidate.alder_ar)),
        ("Område", candidate.omrade or "—"),
        ("Resultat", _format_resultat(candidate.resultat, locale=locale)),
        ("Omsättning", _format_sek(candidate.omsattning_sek, locale=locale)),
        ("Anställda", str(candidate.anstallda) if candidate.anstallda is not None else "—"),
    ]


def _candidate_html(candidate: DdCandidateCompany, *, locale: ReportLocale) -> str:
    rows = _candidate_meta_rows(candidate, locale=locale)
    cells = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in rows
    )
    desc = candidate.beskrivning.strip()
    desc_html = ""
    if desc:
        desc_html = f'<p class="sec-intro">{escape(desc)}</p>'
    heading = "Candidate" if locale == "en" else "Kandidat"
    return f"""
<section class="section" id="kandidat">
  <div class="eyebrow">{heading}</div>
  <h2>{escape(candidate.namn)}</h2>
  {desc_html}
  <table class="stats-table">
    <tbody>{cells}</tbody>
  </table>
</section>
"""


def _dissensus_banner(notes: list[DdDissensusNote], *, locale: ReportLocale) -> str:
    if not notes:
        return ""
    items = "".join(
        f"<li><strong>{escape(n.sub_question_label)}</strong> — "
        f"{n.min_score}–{n.max_score} ({locale == 'en' and 'spread' or 'spridning'} {n.spread})</li>"
        for n in notes
    )
    title = "Dissensus between experts" if locale == "en" else "Dissensus mellan experter"
    intro = (
        "The following sub-questions had score spread ≥ 3 between experts."
        if locale == "en"
        else "Följande delfrågor hade poängspridning ≥ 3 mellan experter."
    )
    return f"""
<div class="explainer ag-warn">
  <strong>{title}</strong>
  <p>{intro}</p>
  <ul class="rec-list">{items}</ul>
</div>
"""


def _scores_by_sub_question(scores: list[DdExpertScore]) -> dict[str, list[DdExpertScore]]:
    grouped: dict[str, list[DdExpertScore]] = defaultdict(list)
    for row in scores:
        grouped[row.sub_question_id].append(row)
    return grouped


def _sub_question_sections(
    result: DdPanelResult,
    *,
    locale: ReportLocale,
    dissensus_ids: set[str],
) -> str:
    grouped = _scores_by_sub_question(result.scores)
    parts: list[str] = []
    heading = "Scores by sub-question" if locale == "en" else "Poäng per delfråga"
    parts.append(f'<section class="section" id="delfragor"><div class="eyebrow">{heading}</div><h2>{heading}</h2>')
    for sq in DD_SUB_QUESTIONS:
        rows = grouped.get(sq.id, [])
        if not rows:
            continue
        dissensus_class = " dissensus" if sq.id in dissensus_ids else ""
        badge = ""
        if sq.id in dissensus_ids:
            badge = (
                '<span class="badge indicated">'
                + ("Dissensus" if locale == "en" else "Dissensus")
                + "</span>"
            )
        cards = []
        for row in rows:
            cards.append(
                f"""
<div class="ag-card{dissensus_class}">
  <div class="ag-name">{escape(row.expert_label)}</div>
  <div class="ag-score-v">{row.score}/10</div>
  {_source_badge_html(row.source)}
  <blockquote class="ag-quote">{escape(row.motivation)}</blockquote>
</div>
"""
            )
        parts.append(
            f"""
<h3 id="delfraga-{escape(sq.id)}">{escape(sq.label)} {badge}</h3>
<div class="ag-grid">{"".join(cards)}</div>
"""
        )
    parts.append("</section>")
    return "".join(parts)


def _raw_score_table(result: DdPanelResult, *, locale: ReportLocale) -> str:
    experts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in result.scores:
        if row.expert_slot_id not in seen:
            seen.add(row.expert_slot_id)
            experts.append((row.expert_slot_id, row.expert_label))

    by_key: dict[tuple[str, str], DdExpertScore] = {}
    for row in result.scores:
        by_key[(row.expert_slot_id, row.sub_question_id)] = row

    dissensus_ids = {n.sub_question_id for n in result.dissensus}
    header_cells = "".join(
        f'<th class="{"dissensus-col" if sq.id in dissensus_ids else ""}">'
        f"{escape(sq.label)}</th>"
        for sq in DD_SUB_QUESTIONS
    )
    body_rows = []
    for slot_id, label in experts:
        cells = []
        for sq in DD_SUB_QUESTIONS:
            score_row = by_key.get((slot_id, sq.id))
            if score_row is None:
                cells.append("<td>—</td>")
            else:
                cells.append(
                    f'<td><strong>{score_row.score}</strong>/10 '
                    f"{_source_badge_html(score_row.source)}</td>"
                )
        body_rows.append(
            f"<tr><th>{escape(label)}</th>{''.join(cells)}</tr>"
        )

    title = "Raw score matrix" if locale == "en" else "Rådata — poängmatris"
    note = (
        "Unweighted expert scores (1–10). No hidden weighting."
        if locale == "en"
        else "Ovägda expertpoäng (1–10). Ingen dold viktning."
    )
    return f"""
<section class="section" id="poangmatris">
  <div class="eyebrow">{title}</div>
  <h2>{title}</h2>
  <p class="sec-intro">{note}</p>
  <div class="table-scroll">
    <table class="stats-table dd-matrix">
      <thead><tr><th>{escape("Expert" if locale == "en" else "Expert")}</th>{header_cells}</tr></thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>
  </div>
</section>
"""


def _sources_appendix(scores: list[DdExpertScore], *, locale: ReportLocale) -> str:
    kinds: dict[str, set[str]] = defaultdict(set)
    for row in scores:
        kinds[row.source.kind].add(row.source.label)
    if not kinds:
        return ""
    title = "Source appendix" if locale == "en" else "Källbilaga"
    intro = (
        "Unique source kinds referenced in this report."
        if locale == "en"
        else "Unika källtyper som refereras i rapporten."
    )
    items = []
    for kind in ("okf", "web", "llm"):
        labels = sorted(kinds.get(kind, []))
        if not labels:
            continue
        badge = _source_badge_html(SourceBadge(kind=kind, label=labels[0], detail=""))
        label_list = ", ".join(escape(l) for l in labels)
        items.append(f"<li>{badge} {label_list}</li>")
    return f"""
<section class="section appendix" id="kallbilaga">
  <div class="eyebrow">{title}</div>
  <h2>{title}</h2>
  <p class="sec-intro">{intro}</p>
  <ul class="rec-list">{"".join(items)}</ul>
</section>
"""


def render_dd_html(
    result: DdPanelResult,
    *,
    title: str,
    locale: ReportLocale,
    session_id: str,
    candidate_id: str,
) -> str:
    lang = "en" if locale == "en" else "sv"
    dissensus_ids = {n.sub_question_id for n in result.dissensus}
    page_title = title.strip() or result.candidate.namn
    eyebrow = "DD REPORT" if locale == "en" else "DD-RAPPORT"
    summary_heading = "Summary" if locale == "en" else "Sammanfattning"
    html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{escape(page_title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="{REPORT_FONTS_HREF}" rel="stylesheet"/>
<style>
/*@@REPORT_THEME_CSS@@*/
.ag-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin-bottom: 28px; }}
.ag-card {{ background: var(--surface-page); border: 1px solid var(--border-hairline); border-radius: var(--radius-md); padding: 16px 18px; }}
.ag-card.dissensus {{ border-color: var(--warm-orange); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--warm-orange) 35%, transparent); }}
.table-scroll {{ overflow-x: auto; }}
.dd-matrix td, .dd-matrix th {{ vertical-align: top; }}
.dd-matrix .badge {{ margin-left: 6px; margin-bottom: 0; }}
th.dissensus-col {{ color: var(--warm-orange); }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">{eyebrow}</div>
  <h1>{escape(page_title)}</h1>
  {_dissensus_banner(result.dissensus, locale=locale)}
  <section class="section" id="sammanfattning">
    <div class="eyebrow">{summary_heading}</div>
    <h2>{summary_heading}</h2>
    <div class="explainer">{escape(result.summary)}</div>
  </section>
  {_candidate_html(result.candidate, locale=locale)}
  {_sub_question_sections(result, locale=locale, dissensus_ids=dissensus_ids)}
  {_raw_score_table(result, locale=locale)}
  {_sources_appendix(result.scores, locale=locale)}
  <p class="meta">session={escape(session_id)} · candidate={escape(candidate_id)}</p>
</div>
<script>
window.addEventListener("message", function(ev) {{
  var data = ev.data;
  if (!data || data.type !== "spinndoctor-scroll" || typeof data.id !== "string") return;
  var el = document.getElementById(data.id);
  if (el) el.scrollIntoView({{ behavior: "smooth", block: "start" }});
}});
</script>
</body>
</html>
"""
    return inject_report_theme(html)


async def generate_dd_report_html(
    result: DdPanelResult,
    *,
    session_id: str,
    candidate_id: str,
    out_dir: Path,
    title: str = "",
    locale: str = "sv",
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    """Write report.html + slots.json + dd.json for a succeeded dd_panel session."""
    loc = normalize_locale(locale)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_dd_html(
        result,
        title=title,
        locale=loc,
        session_id=session_id,
        candidate_id=candidate_id,
    )
    html_path = out_dir / "report.html"
    slots_path = out_dir / "report.slots.json"
    dd_path = out_dir / "report.dd.json"

    dd_doc = {
        "mode": "dd",
        "locale": loc,
        "session_id": session_id,
        "candidate_id": candidate_id,
        "protocol": result.protocol,
        "candidate": result.candidate.model_dump(mode="json"),
        "scores": [s.model_dump(mode="json") for s in result.scores],
        "dissensus": [d.model_dump(mode="json") for d in result.dissensus],
        "summary": result.summary,
    }
    slots_doc = {
        "title": title,
        "locale": loc,
        "mode": "dd",
        "sources": [
            {
                "type": "dd_session",
                "session_id": session_id,
                "candidate_id": candidate_id,
            }
        ],
        "result": dd_doc,
    }

    html_path.write_text(html, encoding="utf-8")
    slots_path.write_text(json.dumps(slots_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    dd_path.write_text(json.dumps(dd_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return html_path, slots_path, slots_doc, dd_doc
