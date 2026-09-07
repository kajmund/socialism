"""Shared legal-memo payload + renderer.

Rättsunderlag and (later) Offentlig Upphandling both map onto this shape.
Do not add module-specific appeal fields here without making them optional.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.report.locale import ReportLocale, normalize_locale
from app.services.report.markdown_html import markdown_to_html
from app.services.report.render import REPORT_FONTS_HREF, inject_report_theme

SourcingStatus = Literal["complete", "partial", "no_sources_found"]

REPORT_FORMAT = "rattsutredning"


def _require_ref(value: str, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


class LagtextRef(BaseModel):
    sfs_id: str
    rubrik: str = ""
    utdrag: str = ""
    url: str | None = None
    forarbete_referens: str | None = None

    @field_validator("sfs_id")
    @classmethod
    def require_sfs_id(cls, value: str) -> str:
        return _require_ref(value, field="sfs_id")


class PraxisRef(BaseModel):
    referens: str
    instans: str = ""
    utdrag: str = ""
    url: str | None = None

    @field_validator("referens")
    @classmethod
    def require_referens(cls, value: str) -> str:
        return _require_ref(value, field="referens")


class ForarbeteRef(BaseModel):
    referens: str
    titel: str = ""
    utdrag: str = ""
    url: str | None = None

    @field_validator("referens")
    @classmethod
    def require_forarbete_referens(cls, value: str) -> str:
        return _require_ref(value, field="referens")


class RattsutredningPayload(BaseModel):
    """Legal memorandum input shared by Rättsunderlag and future OU appeals."""

    fraga: str
    lagtext: list[LagtextRef] = Field(default_factory=list)
    praxis: list[PraxisRef] = Field(default_factory=list)
    forarbeten: list[ForarbeteRef] = Field(default_factory=list)
    sammanfattning: str = ""
    sourcing_status: SourcingStatus


def compute_sourcing_status(
    *,
    lagtext: list[LagtextRef],
    praxis: list[PraxisRef],
    forarbeten: list[ForarbeteRef],
    unanswered: list[str] | None = None,
    empty_queries: list[str] | None = None,
) -> SourcingStatus:
    hits = len(lagtext) + len(praxis) + len(forarbeten)
    if hits == 0:
        return "no_sources_found"
    if unanswered or empty_queries:
        return "partial"
    return "complete"


def _copy(*, locale: ReportLocale) -> dict[str, str]:
    if locale == "en":
        return {
            "eyebrow": "LEGAL MEMORANDUM",
            "question": "Question",
            "law": "Applicable legislation",
            "case_law": "Case law",
            "travaux": "Travaux préparatoires",
            "assessment": "Assessment",
            "no_law": "No statutory sources were retrieved.",
            "no_case": "No case law was retrieved.",
            "no_travaux": "No travaux préparatoires were retrieved.",
            "status_complete": "Source coverage: complete",
            "status_partial": "Source coverage: partial",
            "status_none": "Source coverage: no sources found",
        }
    return {
        "eyebrow": "RÄTTSUTREDNING",
        "question": "Fråga",
        "law": "Tillämplig lagstiftning",
        "case_law": "Praxis",
        "travaux": "Förarbeten",
        "assessment": "Bedömning",
        "no_law": "Inga lagrum hämtades.",
        "no_case": "Ingen praxis hämtades.",
        "no_travaux": "Inga förarbeten hämtades.",
        "status_complete": "Källtäckning: komplett",
        "status_partial": "Källtäckning: partiell",
        "status_none": "Källtäckning: inga källor hittades",
    }


def _status_label(labels: dict[str, str], status: SourcingStatus) -> str:
    if status == "complete":
        return labels["status_complete"]
    if status == "partial":
        return labels["status_partial"]
    if status == "no_sources_found":
        return labels["status_none"]
    raise ValueError(f"Unknown sourcing_status: {status}")


def _ref_lines_md(
    items: list[LagtextRef] | list[PraxisRef] | list[ForarbeteRef],
    *,
    empty: str,
) -> str:
    if not items:
        return empty
    lines: list[str] = []
    for item in items:
        if isinstance(item, LagtextRef):
            heading = f"**{item.sfs_id}**"
            if item.rubrik:
                heading += f" — {item.rubrik}"
            body = item.utdrag.strip()
        elif isinstance(item, PraxisRef):
            heading = f"**{item.referens}**"
            if item.instans:
                heading += f" ({item.instans})"
            body = item.utdrag.strip()
        else:
            heading = f"**{item.referens}**"
            if item.titel:
                heading += f" — {item.titel}"
            body = item.utdrag.strip()
        block = heading
        if body:
            block += f"\n\n{body}"
        if item.url:
            block += f"\n\n{item.url}"
        lines.append(block)
    return "\n\n".join(lines)


def render_rattsutredning_markdown(
    payload: RattsutredningPayload,
    *,
    locale: str = "sv",
) -> str:
    loc = normalize_locale(locale)
    labels = _copy(locale=loc)
    parts = [
        f"# {labels['eyebrow'].title()}",
        "",
        f"## {labels['question']}",
        "",
        payload.fraga.strip(),
        "",
        f"*{_status_label(labels, payload.sourcing_status)}*",
        "",
        f"## {labels['law']}",
        "",
        _ref_lines_md(payload.lagtext, empty=labels["no_law"]),
        "",
        f"## {labels['case_law']}",
        "",
        _ref_lines_md(payload.praxis, empty=labels["no_case"]),
        "",
        f"## {labels['travaux']}",
        "",
        _ref_lines_md(payload.forarbeten, empty=labels["no_travaux"]),
        "",
        f"## {labels['assessment']}",
        "",
        payload.sammanfattning.strip() or labels["no_law"],
        "",
    ]
    return "\n".join(parts)


def _section_html(title: str, body_md: str) -> str:
    return (
        f'<section class="section">'
        f'<div class="eyebrow">{escape(title)}</div>'
        f"<h2>{escape(title)}</h2>"
        f'<div class="explainer md-body">{markdown_to_html(body_md)}</div>'
        f"</section>"
    )


def render_rattsutredning_html(
    payload: RattsutredningPayload,
    *,
    title: str,
    locale: str = "sv",
) -> str:
    loc = normalize_locale(locale)
    labels = _copy(locale=loc)
    lang = "en" if loc == "en" else "sv"
    page_title = title.strip() or labels["eyebrow"].title()
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
.ag-card {{ background: var(--surface-page); border: 1px solid var(--border-hairline); border-radius: var(--radius-md); padding: 16px 18px; margin-bottom: 14px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">{escape(labels["eyebrow"])}</div>
  <h1>{escape(page_title)}</h1>
  {_section_html(labels["question"], payload.fraga)}
  <p class="meta">{escape(_status_label(labels, payload.sourcing_status))}</p>
  {_section_html(labels["law"], _ref_lines_md(payload.lagtext, empty=labels["no_law"]))}
  {_section_html(labels["case_law"], _ref_lines_md(payload.praxis, empty=labels["no_case"]))}
  {_section_html(labels["travaux"], _ref_lines_md(payload.forarbeten, empty=labels["no_travaux"]))}
  {_section_html(labels["assessment"], payload.sammanfattning.strip() or labels["no_law"])}
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


def write_rattsutredning_artifacts(
    payload: RattsutredningPayload,
    *,
    out_dir: Path,
    title: str,
    locale: str,
    source_type: str,
    session_id: str,
    mode: str,
    artifact_name: str = "report.rattsutredning.json",
) -> tuple[Path, Path, dict[str, object]]:
    loc = normalize_locale(locale)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_rattsutredning_html(payload, title=title, locale=loc)
    html_path = out_dir / "report.html"
    slots_path = out_dir / "report.slots.json"
    payload_path = out_dir / artifact_name
    doc = payload.model_dump()
    slots_doc = {
        "title": title,
        "locale": loc,
        "mode": mode,
        "report_format": REPORT_FORMAT,
        "sources": [{"type": source_type, "session_id": session_id}],
        "result": doc,
    }
    html_path.write_text(html, encoding="utf-8")
    slots_path.write_text(json.dumps(slots_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    payload_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return html_path, slots_path, slots_doc
