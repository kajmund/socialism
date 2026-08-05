"""Orchestrate hybrid report generation: metrics charts + LLM narrative."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.report.agent import (
    fill_slot_batch,
    group_questions_into_batches,
    metrics_digest,
)
from app.services.report.bundles import RunBundle, is_ab_comparison
from app.services.report.charts import prefill_chart_slots
from app.services.report.classify import classify_bundles, meta_topics_line
from app.services.report.locale import (
    ReportLocale,
    ab_meta_tests,
    narrative_defaults,
    normalize_locale,
    questions_path,
    template_path,
)
from app.services.report.metrics import compute_report_metrics
from app.services.report.render import (
    apply_slots,
    dry_run_defaults,
    list_slots_in_template,
    load_template,
)
from app.services.report.sanitize import sanitize_slot_output
from app.services.report.tools import ReportToolBundle

logger = logging.getLogger(__name__)


def _load_questions(locale: ReportLocale) -> list[dict[str, Any]]:
    data = json.loads(questions_path(locale).read_text(encoding="utf-8"))
    return list(data.get("questions") or [])


async def fill_narrative_slots(
    *,
    tools: ReportToolBundle,
    questions: list[dict[str, Any]],
    dry_run: bool,
    locale: ReportLocale,
    prompts: dict[str, str],
) -> dict[str, str]:
    if dry_run:
        return {}

    digest = metrics_digest(tools, locale=locale)
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
                locale=locale,
                prompts=prompts,
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
    locale: str = "sv",
    prompts: dict[str, str],
) -> tuple[Path, Path, dict[str, str]]:
    """Write report.html + slots.json under out_dir. Returns (html_path, slots_path, slots)."""
    loc = normalize_locale(locale)
    out_dir.mkdir(parents=True, exist_ok=True)
    classifications = await classify_bundles(bundles, locale=loc, prompts=prompts)
    metrics = compute_report_metrics(bundles, classifications)
    chart_slots = prefill_chart_slots(metrics, locale=loc)
    tools = ReportToolBundle(bundles, metrics)
    questions = _load_questions(loc)

    template = load_template(template_path(loc))
    needed = list_slots_in_template(template)
    slots = dry_run_defaults(needed, locale=loc)
    slots.update(narrative_defaults(chart_slots, bundles, loc))
    slots.update(chart_slots)
    slots["meta_topics"] = meta_topics_line(classifications, locale=loc)
    if is_ab_comparison(bundles):
        slots["meta_tests"] = ab_meta_tests(loc)
    slots["meta_date"] = datetime.now(tz=UTC).date().isoformat()
    if title.strip():
        slots["page_title"] = title.strip()

    narrative = await fill_narrative_slots(
        tools=tools,
        questions=questions,
        dry_run=dry_run,
        locale=loc,
        prompts=prompts,
    )
    for k, v in narrative.items():
        if v:
            slots[k] = v

    # Ensure chart slots never overwritten by empty LLM
    slots.update(chart_slots)
    slots["meta_topics"] = meta_topics_line(classifications, locale=loc)
    if is_ab_comparison(bundles):
        slots["meta_tests"] = ab_meta_tests(loc)
    slots["meta_date"] = datetime.now(tz=UTC).date().isoformat()

    html = apply_slots(template, slots)
    html_path = out_dir / "report.html"
    slots_path = out_dir / "report.slots.json"
    html_path.write_text(html, encoding="utf-8")
    slots_path.write_text(
        json.dumps(
            {
                "title": title,
                "locale": loc,
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
