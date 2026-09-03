"""Template-based expertgranskning report from a generic_panel session."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from app.services.expertgranskning import ARTIFACT_NAME, REPORT_MODE, SOURCE_TYPE
from app.services.report.locale import ReportLocale, normalize_locale
from app.services.report.markdown_html import markdown_to_html
from app.services.report.render import REPORT_FONTS_HREF, inject_report_theme


def load_expertgranskning_report_json(report_id: str) -> dict[str, Any] | None:
    from app.services.report import ARTIFACT_ROOT

    path = Path(ARTIFACT_ROOT) / report_id / ARTIFACT_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _copy(*, locale: ReportLocale) -> dict[str, str]:
    if locale == "en":
        return {
            "eyebrow": "EXPERT REVIEW",
            "document": "Document",
            "summary": "Summary",
            "transcript": "Panel transcript",
        }
    return {
        "eyebrow": "EXPERTGRANSKNING",
        "document": "Dokument",
        "summary": "Sammanfattning",
        "transcript": "Panelens turer",
    }


def _transcript_html(turns: list[dict[str, Any]]) -> str:
    items: list[str] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        phase = str(turn.get("phase") or "")
        if phase == "scratchpad":
            continue
        speaker = escape(str(turn.get("speaker") or ""))
        content = markdown_to_html(str(turn.get("content") or ""))
        if not speaker and not content:
            continue
        items.append(
            f'<article class="ag-card">'
            f'<div class="eyebrow">{speaker}</div>'
            f'<div class="explainer md-body">{content}</div>'
            f"</article>"
        )
    return "".join(items)


def render_expertgranskning_html(
    *,
    title: str,
    locale: ReportLocale,
    document_text: str,
    summary: str,
    transcript: list[dict[str, Any]],
    session_id: str,
) -> str:
    labels = _copy(locale=locale)
    lang = "en" if locale == "en" else "sv"
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
  <div class="eyebrow">{labels["eyebrow"]}</div>
  <h1>{escape(page_title)}</h1>
  <section class="section" id="dokument">
    <div class="eyebrow">{labels["document"]}</div>
    <h2>{labels["document"]}</h2>
    <div class="explainer md-body">{markdown_to_html(document_text)}</div>
  </section>
  <section class="section" id="sammanfattning">
    <div class="eyebrow">{labels["summary"]}</div>
    <h2>{labels["summary"]}</h2>
    <div class="explainer md-body">{markdown_to_html(summary)}</div>
  </section>
  <section class="section" id="transkript">
    <div class="eyebrow">{labels["transcript"]}</div>
    <h2>{labels["transcript"]}</h2>
    {_transcript_html(transcript)}
  </section>
  <p class="meta">session={escape(session_id)}</p>
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


def write_expertgranskning_artifacts(
    *,
    out_dir: Path,
    title: str,
    locale: str,
    session_id: str,
    panel_id: int | None,
    document_text: str,
    summary: str,
    transcript: list[dict[str, Any]],
) -> tuple[Path, Path, dict[str, Any]]:
    loc = normalize_locale(locale)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_expertgranskning_html(
        title=title,
        locale=loc,
        document_text=document_text,
        summary=summary,
        transcript=transcript,
        session_id=session_id,
    )
    html_path = out_dir / "report.html"
    slots_path = out_dir / "report.slots.json"
    payload_path = out_dir / ARTIFACT_NAME
    payload = {
        "mode": REPORT_MODE,
        "locale": loc,
        "session_id": session_id,
        "panel_id": panel_id,
        "title": title,
        "document_text": document_text,
        "summary": summary,
        "transcript": transcript,
    }
    slots_doc = {
        "title": title,
        "locale": loc,
        "mode": REPORT_MODE,
        "sources": [{"type": SOURCE_TYPE, "session_id": session_id}],
        "result": payload,
    }
    html_path.write_text(html, encoding="utf-8")
    slots_path.write_text(json.dumps(slots_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return html_path, slots_path, payload
