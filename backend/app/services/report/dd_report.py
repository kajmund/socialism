"""Template-based DD report: render DdPanelResult from panel session."""

from __future__ import annotations

import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from app.services.dd.schemas import DdAccountYear, DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge, SourceKind
from app.services.dd.sub_questions import SubQuestionRef
from app.services.panel.schemas import (
    DdDissensusNote,
    DdExpertScore,
    DdPanelResult,
    DdUnansweredNote,
)
from app.services.report.locale import ReportLocale, normalize_locale
from app.services.report.markdown_html import markdown_to_html
from app.services.report.render import REPORT_FONTS_HREF, inject_report_theme
from app.services.spindoctor_dd import sub_questions_from_dd_doc

_SOURCE_BADGE_CLASS: dict[SourceKind, str] = {
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


def _yes_no(value: bool | None, *, locale: ReportLocale) -> str | None:
    if value is None:
        return None
    if locale == "en":
        return "Yes" if value else "No"
    return "Ja" if value else "Nej"


def _candidate_meta_rows(candidate: DdCandidateCompany, *, locale: ReportLocale) -> list[tuple[str, str]]:
    en = locale == "en"
    rows = [
        ("Company" if en else "Bolag", candidate.namn),
        ("Org. no." if en else "Org.nr", candidate.organisationsnummer),
        ("Age (years)" if en else "Ålder (år)", str(candidate.alder_ar)),
        ("Region" if en else "Område", candidate.omrade or "—"),
        ("Result" if en else "Resultat", _format_resultat(candidate.resultat, locale=locale)),
        ("Revenue" if en else "Omsättning", _format_sek(candidate.omsattning_sek, locale=locale)),
        (
            "Employees" if en else "Anställda",
            str(candidate.anstallda) if candidate.anstallda is not None else "—",
        ),
    ]
    for label_en, label_sv, value in (
        ("F-tax", "F-skatt", _yes_no(candidate.fskatt, locale=locale)),
        ("VAT", "Moms", _yes_no(candidate.moms, locale=locale)),
        (
            "Employer contributions",
            "Arbetsgivaravgift",
            _yes_no(candidate.arbetsgivaravgift, locale=locale),
        ),
    ):
        if value is not None:
            rows.append((label_en if en else label_sv, value))
    if candidate.koncern_bolag is not None or candidate.koncern_dotter is not None:
        companies = candidate.koncern_bolag if candidate.koncern_bolag is not None else "—"
        subsidiaries = candidate.koncern_dotter if candidate.koncern_dotter is not None else "—"
        rows.append(
            (
                "Group" if en else "Koncern",
                (
                    f"{companies} companies, {subsidiaries} subsidiaries"
                    if en
                    else f"{companies} bolag, {subsidiaries} dotterbolag"
                ),
            )
        )
    if candidate.moderbolag:
        rows.append(("Parent company" if en else "Moderbolag", candidate.moderbolag))
    if candidate.telefon:
        rows.append(("Phone" if en else "Telefon", candidate.telefon))
    for label_en, label_sv, value in (
        ("Floating charge", "Företagshypotek", _yes_no(candidate.foretagshypotek, locale=locale)),
        (
            "Payment remark",
            "Betalningsanmärkning",
            _yes_no(candidate.betalningsanmarkning, locale=locale),
        ),
        ("Gazelle", "Gasell", _yes_no(candidate.gasell, locale=locale)),
    ):
        if value is not None:
            rows.append((label_en if en else label_sv, value))
    return rows


_CHART_W = 320
_CHART_H = 188
_CHART_PAD = (44, 10, 18, 28)  # left, right, top, bottom


def _short_number(value: float, *, decimals: int = 1) -> str:
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _format_sek_short(value: int | float, *, locale: ReportLocale) -> str:
    sign = "−" if value < 0 else ""
    n = abs(float(value))
    if n >= 1_000_000_000:
        amount = _short_number(n / 1_000_000_000)
        return f"{sign}{amount} mdkr" if locale == "sv" else f"{sign}{amount} bn SEK"
    if n >= 1_000_000:
        amount = _short_number(n / 1_000_000)
        return f"{sign}{amount} mkr" if locale == "sv" else f"{sign}{amount} M SEK"
    if n >= 1_000:
        amount = _short_number(n / 1_000, decimals=0)
        return f"{sign}{amount} tkr" if locale == "sv" else f"{sign}{amount}k SEK"
    return _format_sek(int(value), locale=locale)


def _sorted_account_years(years: list[DdAccountYear]) -> list[DdAccountYear]:
    def sort_key(year: DdAccountYear) -> tuple[int, str]:
        digits = "".join(ch for ch in year.year if ch.isdigit())
        return (int(digits[:4]) if len(digits) >= 4 else 0, year.year)

    return sorted(years, key=sort_key)


def _parse_pct(raw: str | None) -> float | None:
    if not raw:
        return None
    text = raw.strip().replace("%", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _year_column_chart(
    labels: list[str],
    values: list[float | None],
    *,
    title: str,
    color: str,
    format_tick,
    signed: bool = False,
) -> str:
    present = [v for v in values if v is not None]
    if not present:
        return ""
    max_v = max(present)
    min_v = min(present)
    if signed:
        max_v = max(0.0, max_v)
        min_v = min(0.0, min_v)
    else:
        max_v = max(0.0, max_v)
        min_v = 0.0
    if max_v == min_v:
        max_v = min_v + 1.0
    pad_l, pad_r, pad_t, pad_b = _CHART_PAD
    plot_w = _CHART_W - pad_l - pad_r
    plot_h = _CHART_H - pad_t - pad_b
    span = max_v - min_v

    def y_of(value: float) -> float:
        return pad_t + (max_v - value) / span * plot_h

    zero_y = y_of(0.0)
    ticks = [max_v]
    if min_v < 0 < max_v:
        ticks.append(0.0)
    ticks.append(min_v)
    axis = []
    for tick in ticks:
        y = y_of(tick)
        axis.append(
            f'<line class="dd-chart-grid" x1="{pad_l}" y1="{y:.1f}" '
            f'x2="{_CHART_W - pad_r}" y2="{y:.1f}"/>'
            f'<text class="dd-chart-tick" x="{pad_l - 6}" y="{y + 3:.1f}" '
            f'text-anchor="end">{escape(format_tick(tick))}</text>'
        )
    slot = plot_w / max(len(labels), 1)
    bar_w = min(36.0, slot * 0.55)
    bars = []
    year_labels = []
    for i, (label, raw) in enumerate(zip(labels, values, strict=True)):
        cx = pad_l + slot * i + slot / 2
        year_labels.append(
            f'<text class="dd-chart-year" x="{cx:.1f}" y="{_CHART_H - 8}" '
            f'text-anchor="middle">{escape(label)}</text>'
        )
        if raw is None:
            continue
        y = y_of(raw)
        top = min(y, zero_y)
        height = abs(zero_y - y)
        if height < 2:
            height = 2
            top = zero_y - 2 if raw >= 0 else zero_y
        fill = color
        if signed and raw < 0:
            fill = "var(--db-error)"
        label_y = top - 4 if raw >= 0 else top + height + 11
        bars.append(
            f'<rect class="dd-chart-bar" x="{cx - bar_w / 2:.1f}" y="{top:.1f}" '
            f'width="{bar_w:.1f}" height="{height:.1f}" rx="3" fill="{fill}"/>'
            f'<text class="dd-chart-val" x="{cx:.1f}" y="{label_y:.1f}" '
            f'text-anchor="middle">{escape(format_tick(raw))}</text>'
        )
    aria = escape(f"{title}: " + ", ".join(
        f"{lab} {format_tick(val)}" for lab, val in zip(labels, values, strict=True) if val is not None
    ))
    return f"""
<figure class="chart-card dd-year-chart">
  <h4>{escape(title)}</h4>
  <svg viewBox="0 0 {_CHART_W} {_CHART_H}" role="img" aria-label="{aria}">
    {"".join(axis)}
    <line class="dd-chart-zero" x1="{pad_l}" y1="{zero_y:.1f}" x2="{_CHART_W - pad_r}" y2="{zero_y:.1f}"/>
    {"".join(bars)}
    {"".join(year_labels)}
  </svg>
</figure>
"""


def _accounts_table_html(years: list[DdAccountYear], *, locale: ReportLocale) -> str:
    en = locale == "en"
    rows: list[tuple[str, list[str]]] = [
        ("Revenue" if en else "Omsättning", [_format_sek(y.omsattning_sek, locale=locale) for y in years]),
        ("Result" if en else "Resultat", [_format_sek(y.resultat_sek, locale=locale) for y in years]),
        ("EBITDA", [_format_sek(y.ebitda_sek, locale=locale) for y in years]),
        (
            "Proposed dividend" if en else "Föreslagen utdelning",
            [_format_sek(y.utdelning_sek, locale=locale) for y in years],
        ),
        (
            "Employees" if en else "Anställda",
            [str(y.anstallda) if y.anstallda is not None else "—" for y in years],
        ),
        (
            "Equity" if en else "Eget kapital",
            [_format_sek(y.eget_kapital_sek, locale=locale) for y in years],
        ),
        (
            "Solidity" if en else "Soliditet",
            [f"{y.soliditet_pct}%" if y.soliditet_pct else "—" for y in years],
        ),
    ]
    useful = [row for row in rows if any(cell != "—" for cell in row[1])]
    if not useful:
        return ""
    head = "".join(f"<th>{escape(year.year)}</th>" for year in years)
    body = "".join(
        "<tr><th>"
        + escape(label)
        + "</th>"
        + "".join(f"<td>{escape(cell)}</td>" for cell in cells)
        + "</tr>"
        for label, cells in useful
    )
    metric = "Metric" if en else "Nyckeltal"
    return f"""
<div class="table-scroll">
  <table class="stats-table dd-accounts-table">
    <thead><tr><th>{escape(metric)}</th>{head}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</div>
"""


def _accounts_html(years: list[DdAccountYear], *, locale: ReportLocale) -> str:
    ordered = _sorted_account_years(years)
    if not ordered:
        return ""
    en = locale == "en"
    labels = [year.year for year in ordered]
    charts = [
        _year_column_chart(
            labels,
            [float(y.omsattning_sek) if y.omsattning_sek is not None else None for y in ordered],
            title="Revenue" if en else "Omsättning",
            color="var(--db-ink-950)",
            format_tick=lambda v: _format_sek_short(v, locale=locale),
        ),
        _year_column_chart(
            labels,
            [float(y.resultat_sek) if y.resultat_sek is not None else None for y in ordered],
            title="Result" if en else "Resultat",
            color="var(--db-success)",
            format_tick=lambda v: _format_sek_short(v, locale=locale),
            signed=True,
        ),
        _year_column_chart(
            labels,
            [float(y.ebitda_sek) if y.ebitda_sek is not None else None for y in ordered],
            title="EBITDA",
            color="var(--db-gold-700)",
            format_tick=lambda v: _format_sek_short(v, locale=locale),
            signed=True,
        ),
        _year_column_chart(
            labels,
            [float(y.utdelning_sek) if y.utdelning_sek is not None else None for y in ordered],
            title="Proposed dividend" if en else "Föreslagen utdelning",
            color="var(--warm-orange)",
            format_tick=lambda v: _format_sek_short(v, locale=locale),
        ),
        _year_column_chart(
            labels,
            [float(y.eget_kapital_sek) if y.eget_kapital_sek is not None else None for y in ordered],
            title="Equity" if en else "Eget kapital",
            color="var(--db-ink-400)",
            format_tick=lambda v: _format_sek_short(v, locale=locale),
        ),
        _year_column_chart(
            labels,
            [float(y.anstallda) if y.anstallda is not None else None for y in ordered],
            title="Employees" if en else "Anställda",
            color="var(--db-ink-950)",
            format_tick=lambda v: _short_number(v, decimals=0),
        ),
        _year_column_chart(
            labels,
            [_parse_pct(y.soliditet_pct) for y in ordered],
            title="Solidity" if en else "Soliditet",
            color="var(--db-success)",
            format_tick=lambda v: f"{_short_number(v)} %",
        ),
    ]
    chart_html = "".join(part for part in charts if part)
    heading = "Accounts" if en else "Räkenskaper"
    intro = (
        "Key figures compared across financial years."
        if en
        else "Nyckeltal jämförda över räkenskapsåren."
    )
    grid = f'<div class="dd-accounts-grid">{chart_html}</div>' if chart_html else ""
    return (
        f'<div class="dd-accounts" id="rakenskaper">'
        f"<h3>{heading}</h3>"
        f'<p class="sec-intro">{intro}</p>'
        f"{grid}"
        f"{_accounts_table_html(ordered, locale=locale)}"
        f"</div>"
    )


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
    extra_blocks: list[str] = []
    if candidate.styrelse:
        items = "".join(
            f"<li>{escape((officer.roll + ': ') if officer.roll else '')}"
            f"{escape(officer.namn)}"
            f"{escape(f' ({officer.grupp})' if officer.grupp else '')}</li>"
            for officer in candidate.styrelse
        )
        extra_blocks.append(
            f"<h3>{'Board and roles' if locale == 'en' else 'Styrelse och roller'}</h3>"
            f"<ul>{items}</ul>"
        )
    if candidate.firmateckning:
        extra_blocks.append(
            f"<h3>{'Signatory rights' if locale == 'en' else 'Firmateckning'}</h3>"
            f"<p>{escape(' '.join(candidate.firmateckning))}</p>"
        )
    if candidate.varumarken:
        extra_blocks.append(
            f"<h3>{'Trademarks' if locale == 'en' else 'Varumärken'}</h3>"
            f"<p>{escape(', '.join(candidate.varumarken))}</p>"
        )
    for title_en, title_sv, items in (
        ("NACE", "SNI", candidate.sni),
        ("Establishments", "Arbetsställen", candidate.arbetsstallen),
        ("Related companies", "Relaterade bolag", candidate.relaterade_bolag),
        ("Events", "Händelser", candidate.handelser),
    ):
        if items:
            lis = "".join(f"<li>{escape(item)}</li>" for item in items)
            extra_blocks.append(
                f"<h3>{title_en if locale == 'en' else title_sv}</h3><ul>{lis}</ul>"
            )
    if candidate.rakenskaper:
        extra_blocks.append(_accounts_html(candidate.rakenskaper, locale=locale))
    extras_html = "".join(extra_blocks)
    heading = "Candidate" if locale == "en" else "Kandidat"
    return f"""
<section class="section" id="kandidat">
  <div class="eyebrow">{heading}</div>
  <h2>{escape(candidate.namn)}</h2>
  {desc_html}
  <table class="stats-table">
    <tbody>{cells}</tbody>
  </table>
  {extras_html}
</section>
"""


def _unanswered_banner(notes: list[DdUnansweredNote], *, locale: ReportLocale) -> str:
    if not notes:
        return ""
    items = "".join(
        f"<li><strong>{escape(n.sub_question_label)}</strong> — "
        f"{escape(n.moderator_note)}</li>"
        for n in notes
    )
    title = "Unanswered sub-questions" if locale == "en" else "Obesvarade delfrågor"
    intro = (
        "No expert raised a hand for the following sub-questions. Scoring was skipped."
        if locale == "en"
        else "Ingen expert räckte upp handen för följande delfrågor. Poängsättning hoppades över."
    )
    return f"""
<div class="explainer ag-warn" id="obesvarade">
  <strong>{title}</strong>
  <p>{intro}</p>
  <ul class="rec-list">{items}</ul>
</div>
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
    sub_questions: list[SubQuestionRef],
) -> str:
    grouped = _scores_by_sub_question(result.scores)
    parts: list[str] = []
    heading = "Scores by sub-question" if locale == "en" else "Poäng per delfråga"
    parts.append(f'<section class="section" id="delfragor"><div class="eyebrow">{heading}</div><h2>{heading}</h2>')
    for sq in sub_questions:
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


def _raw_score_table(
    result: DdPanelResult,
    *,
    locale: ReportLocale,
    sub_questions: list[SubQuestionRef],
) -> str:
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
    unanswered_ids = {n.sub_question_id for n in result.unanswered}

    def _header_class(question_id: str) -> str:
        classes: list[str] = []
        if question_id in dissensus_ids:
            classes.append("dissensus-col")
        if question_id in unanswered_ids:
            classes.append("unanswered-col")
        return f' class="{" ".join(classes)}"' if classes else ""

    header_cells = "".join(
        f"<th{_header_class(sq.id)}>{escape(sq.label)}</th>"
        for sq in sub_questions
    )
    body_rows = []
    for slot_id, label in experts:
        cells = []
        for sq in sub_questions:
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
    for kind in ("web", "llm"):
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
    sub_questions: list[SubQuestionRef] | None = None,
) -> str:
    lang = "en" if locale == "en" else "sv"
    dissensus_ids = {n.sub_question_id for n in result.dissensus}
    resolved = sub_questions or sub_questions_from_dd_doc(
        {
            "scores": [s.model_dump(mode="json") for s in result.scores],
            "dissensus": [d.model_dump(mode="json") for d in result.dissensus],
            "unanswered": [u.model_dump(mode="json") for u in result.unanswered],
        }
    )
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
th.unanswered-col {{ color: var(--text-muted); font-style: italic; }}
.dd-accounts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin: 12px 0 18px; }}
.dd-year-chart {{ margin: 0; padding: 16px 16px 12px; }}
.dd-year-chart svg {{ width: 100%; height: auto; display: block; }}
.dd-chart-grid {{ stroke: var(--border-hairline); stroke-width: 1; }}
.dd-chart-zero {{ stroke: var(--db-ink-200); stroke-width: 1.25; }}
.dd-chart-tick, .dd-chart-year, .dd-chart-val {{
  font-family: var(--font-body); fill: var(--text-muted);
}}
.dd-chart-tick {{ font-size: 9px; }}
.dd-chart-year {{ font-size: 11px; font-weight: 600; fill: var(--text-body); }}
.dd-chart-val {{ font-size: 9px; font-weight: 600; fill: var(--text-body); }}
.dd-accounts-table th, .dd-accounts-table td {{ white-space: nowrap; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">{eyebrow}</div>
  <h1>{escape(page_title)}</h1>
  {_dissensus_banner(result.dissensus, locale=locale)}
  {_unanswered_banner(result.unanswered, locale=locale)}
  <section class="section" id="sammanfattning">
    <div class="eyebrow">{summary_heading}</div>
    <h2>{summary_heading}</h2>
    <div class="explainer md-body">{markdown_to_html(result.summary)}</div>
  </section>
  {_candidate_html(result.candidate, locale=locale)}
  {_sub_question_sections(result, locale=locale, dissensus_ids=dissensus_ids, sub_questions=resolved)}
  {_raw_score_table(result, locale=locale, sub_questions=resolved)}
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


def render_dd_html_from_artifact(
    out_dir: Path,
    *,
    title: str = "",
    locale: str = "sv",
) -> str | None:
    """Render current HTML from report.dd.json. Remaps stored OKF badges."""
    dd_path = out_dir / "report.dd.json"
    if not dd_path.is_file():
        return None
    doc = json.loads(dd_path.read_text(encoding="utf-8"))
    result = DdPanelResult.model_validate(
        {
            "protocol": doc.get("protocol") or "dd_panel",
            "candidate": doc["candidate"],
            "scores": doc["scores"],
            "dissensus": doc.get("dissensus") or [],
            "unanswered": doc.get("unanswered") or [],
            "summary": doc.get("summary") or "",
        }
    )
    page_title = title.strip()
    if not page_title:
        slots_path = out_dir / "report.slots.json"
        if slots_path.is_file():
            slots = json.loads(slots_path.read_text(encoding="utf-8"))
            page_title = str(slots.get("title") or "")
    return render_dd_html(
        result,
        title=page_title,
        locale=normalize_locale(str(doc.get("locale") or locale)),
        session_id=str(doc.get("session_id") or ""),
        candidate_id=str(doc.get("candidate_id") or result.candidate.id),
    )


async def generate_dd_report_html(
    result: DdPanelResult,
    *,
    session_id: str,
    candidate_id: str,
    out_dir: Path,
    title: str = "",
    locale: str = "sv",
    sub_questions: list[SubQuestionRef] | None = None,
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
        sub_questions=sub_questions,
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
        "unanswered": [u.model_dump(mode="json") for u in result.unanswered],
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
