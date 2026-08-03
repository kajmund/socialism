"""Orchestrate hybrid report generation: metrics charts + LLM narrative."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.report.agent import (
    fill_slot_batch,
    group_questions_into_batches,
    metrics_digest,
)
from app.services.report.bundles import RunBundle, is_ab_comparison
from app.services.report.charts import prefill_chart_slots
from app.services.report.classify import classify_bundles, meta_topics_line
from app.services.report.metrics import compute_report_metrics
from app.services.report.render import (
    ASSETS_DIR,
    apply_slots,
    dry_run_defaults,
    list_slots_in_template,
    load_template,
)
from app.services.report.sanitize import sanitize_slot_output
from app.services.report.tools import ReportToolBundle

logger = logging.getLogger(__name__)


def _load_questions(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or (ASSETS_DIR / "questions.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    return list(data.get("questions") or [])


def narrative_defaults(metrics_slots: dict[str, str], bundles: list[RunBundle]) -> dict[str, str]:
    n = len(bundles)
    labels = ", ".join(b.label for b in bundles)
    ab = is_ab_comparison(bundles)
    compare_intro = (
        "Jämförelse mellan Version A och Version B i samma A/B-test."
        if ab
        else (
            "En enda körning — ingen populationsjämförelse."
            if n == 1
            else f"Jämförelse mellan {n} körningar."
        )
    )
    compare_findings = (
        '<div class="fc neu"><h3>A vs B</h3>'
        "<p>Se jämförelsekorten för skillnader i Gini, ämne och engagemang mellan armarna.</p></div>"
        '<div class="fc cau"><h3>Osäkerhet</h3>'
        "<p>En A/B-körning — tolka skillnader som observation, inte bevis.</p></div>"
        if ab
        else (
            '<div class="fc neu"><h3>Observation</h3>'
            "<p>Se jämförelsekorten för skillnader i Gini och ämne.</p></div>"
            '<div class="fc cau"><h3>Osäkerhet</h3>'
            "<p>Få körningar — tolka skillnader försiktigt.</p></div>"
        )
    )
    return {
        "page_title": (
            f"A/B-rapport — {bundles[0].run_name}" if ab else f"Simuleringsrapport — {labels}"
        ),
        "cover_eyebrow": (
            "Pilottest — A/B meddelandeanalys" if ab else "Pilottest — Meddelandeanalys"
        ),
        "cover_h1": (
            "Vilken budskapsversion fick starkast gensvar?"
            if ab
            else "Hur tas politiska budskap emot av vanliga invånare?"
        ),
        "cover_sub": (
            f"Vi jämförde Version A och Version B i samma simulering "
            f"({metrics_slots.get('chart_agent_count', '?')} medborgare per arm)."
            if ab
            else (
                f"Vi analyserade hur budskap spreds och mottogs i "
                f"{n} simulerad{'e' if n != 1 else ''} körning{'ar' if n != 1 else ''}."
            )
        ),
        "cover_box1_lbl": "Viktigaste insikt",
        "cover_box1_html": (
            f"Engagemanget koncentrerades — "
            f"<strong>{metrics_slots.get('chart_zero_likes', '?')} agenter</strong> "
            "fick inga likes."
        ),
        "cover_box2_lbl": "Vad fungerade",
        "cover_box2_html": (
            "Jämför budskapsstil och likes mellan Version A och B i diagrammen."
            if ab
            else "Se budskapsstil-sektionen för heuristisk ranking efter likes."
        ),
        "cover_box3_lbl": "Vad vi testade",
        "cover_box3_html": (
            f"<strong>A/B</strong> · {metrics_slots.get('chart_agent_count', '?')} medborgare"
            if ab
            else (
                f"<strong>{n}</strong> körning{'ar' if n != 1 else ''} · "
                f"{metrics_slots.get('chart_agent_count', '?')} medborgare"
            )
        ),
        "meta_scenario": bundles[0].run_name if bundles else "Simulering",
        "meta_topics": "Se ämnesfördelning i rapporten",
        "infographic_eyebrow": (
            "Sammanfattning — A/B-test"
            if ab
            else f"Sammanfattning — {n} test{'er' if n != 1 else ''}"
        ),
        "infographic_h2": "Vad visade testerna?",
        "infographic_lead": (
            "Skillnader mellan Version A och Version B i engagemang och ämnesfokus."
            if ab
            else (
                "Ett tydligt mönster i engagemang och ämnesfokus."
                if n == 1
                else f"Jämförelse mellan {n} körningar."
            )
        ),
        "info_conc_1_html": "<strong>Engagemang koncentrerat</strong> — få röster bar majoriteten av likes.",
        "info_conc_2_html": "<strong>Heuristik</strong> — stilranking bygger på nyckelord, inte manuell kodning.",
        "info_conc_3_html": "<strong>Begränsning</strong> — för få körningar för formell statistik.",
        "sec01_intro": (
            "Vi använde ett simuleringsverktyg där AI-agenter debatterar som vanliga medborgare "
            "på sociala medier. Varje agent har yrke, ålder och personlighet."
        ),
        "method_steps_html": (
            '<div class="mstep"><div class="mstep-num">1</div><h4>Medborgare</h4>'
            "<p>Populationen speglas som AI-agenter.</p></div>"
            '<div class="mstep"><div class="mstep-num">2</div><h4>Budskap</h4>'
            "<p>Parti- och nyhetsinlägg injiceras i flödet.</p></div>"
            '<div class="mstep"><div class="mstep-num">3</div><h4>Debatt</h4>'
            "<p>Agenter gillar, kommenterar och ignorerar.</p></div>"
            '<div class="mstep"><div class="mstep-num">4</div><h4>Analys</h4>'
            "<p>Vi mäter engagemang, ton och ämnesdrift.</p></div>"
            '<div class="mstep"><div class="mstep-num">5</div><h4>Jämförelse</h4>'
            f"<p>{'A/B: Version A mot Version B' if ab else ('En körning' if n == 1 else str(n) + ' körningar')} "
            "i denna rapport.</p></div>"
        ),
        "method_explainer_html": (
            "<strong>Varför simulering?</strong> Att testa budskap på riktiga väljare är dyrt. "
            "Resultaten visar tendenser, inte garantier."
        ),
        "sec02_intro": "Engagemanget fördelades ojämnt — en liten grupp bar debatten.",
        "sec02_findings_html": (
            f'<div class="fc neu">{metrics_slots.get("badge_html", "")}'
            f"<div class=\"fc-num\">{metrics_slots.get('chart_zero_likes', '—')}</div>"
            "<h3>Agenter utan likes</h3>"
            "<p>Majoriteten fick litet eller inget engagemang.</p></div>"
            f'<div class="fc cau">{metrics_slots.get("badge_html", "")}'
            f"<div class=\"fc-num\">{metrics_slots.get('chart_gini', '—')}</div>"
            "<h3>Gini för likes</h3>"
            "<p>Högre värde betyder starkare koncentration.</p></div>"
        ),
        "sec03_intro": "Vi grupperade texter heuristiskt efter kommunikationsstil och jämförde snittlikes.",
        "sec03_findings_html": (
            '<div class="fc pos"><h3>Konkret kritik</h3>'
            "<p>Texter med siffror och skarp iakttagelse tenderar att få mer stöd.</p></div>"
            '<div class="fc neu"><h3>Provokation</h3>'
            "<p>Kontrollera stilranking — provocerande språk får ofta lågt engagemang.</p></div>"
        ),
        "sec04_h2": "Ämnesfokus i debatten",
        "sec04_intro": "Ämnesandelar bygger på nyckelord i inlägg och kommentarer.",
        "sec04_explainer_html": (
            "<strong>Vad betyder detta?</strong> Om ett sidospår dominerar kan huvudbudskapet "
            "behöva göras mer konkret och personligt."
        ),
        "sec05_intro": "Några röster samlade mer likes än övriga.",
        "sec06_intro": compare_intro,
        "sec06_findings_html": compare_findings,
    }


async def fill_narrative_slots(
    *,
    tools: ReportToolBundle,
    questions: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, str]:
    if dry_run or not settings.deepseek_api_key:
        return {}

    digest = metrics_digest(tools)
    multi = tools.metrics.n_runs > 1
    batches = group_questions_into_batches(questions)
    if not batches:
        return {}

    results = await asyncio.gather(
        *[
            fill_slot_batch(
                digest=digest,
                multi=multi,
                batch_name=name,
                items=items,
            )
            for name, items in batches
        ]
    )

    out: dict[str, str] = {}
    for batch_map in results:
        for slot, raw in batch_map.items():
            cleaned = sanitize_slot_output(slot, raw)
            if cleaned:
                out[slot] = cleaned
    return out


async def generate_report_html(
    bundles: list[RunBundle],
    *,
    out_dir: Path,
    dry_run: bool = False,
    title: str = "",
) -> tuple[Path, Path, dict[str, str]]:
    """Write report.html + slots.json under out_dir. Returns (html_path, slots_path, slots)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    use_llm = (not dry_run) and bool(settings.deepseek_api_key)
    classifications = await classify_bundles(bundles, use_llm=use_llm)
    metrics = compute_report_metrics(bundles, classifications)
    chart_slots = prefill_chart_slots(metrics)
    tools = ReportToolBundle(bundles, metrics)
    questions = _load_questions()

    template = load_template()
    needed = list_slots_in_template(template)
    slots = dry_run_defaults(needed)
    slots.update(narrative_defaults(chart_slots, bundles))
    slots.update(chart_slots)
    slots["meta_topics"] = meta_topics_line(classifications)
    if is_ab_comparison(bundles):
        slots["meta_tests"] = "A/B · 2 armar"
    slots["meta_date"] = datetime.now(tz=UTC).date().isoformat()
    if title.strip():
        slots["page_title"] = title.strip()

    narrative = await fill_narrative_slots(
        tools=tools,
        questions=questions,
        dry_run=dry_run,
    )
    for k, v in narrative.items():
        if v:
            slots[k] = v

    # Ensure chart slots never overwritten by empty LLM
    slots.update(chart_slots)
    slots["meta_topics"] = meta_topics_line(classifications)
    if is_ab_comparison(bundles):
        slots["meta_tests"] = "A/B · 2 armar"
    slots["meta_date"] = datetime.now(tz=UTC).date().isoformat()

    html = apply_slots(template, slots)
    html_path = out_dir / "report.html"
    slots_path = out_dir / "report.slots.json"
    html_path.write_text(html, encoding="utf-8")
    slots_path.write_text(
        json.dumps(
            {
                "title": title,
                "sources": [
                    {"run_id": b.run_id, "attempt_id": b.attempt_id, "label": b.label}
                    for b in bundles
                ],
                "slots": slots,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return html_path, slots_path, slots
