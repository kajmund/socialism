"""Orchestrate hybrid report generation: metrics charts + LLM narrative."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.config import settings
from app.schemas.domain import DEFAULT_SSR_TEMPERATURE
from app.services.report.agent import (
    fill_slot_batch,
    group_questions_into_batches,
    metrics_digest,
)
from app.services.report.bundles import RunBundle, is_ab_comparison
from app.services.report.charts import prefill_chart_slots
from app.services.report.classify import BundleClassification, classify_bundles, meta_topics_line
from app.services.report.locale import (
    ReportLocale,
    ab_meta_tests,
    narrative_defaults,
    normalize_locale,
    questions_path,
    template_path,
)
from app.services.report.metrics import compute_report_metrics
from app.services.report.quick import build_quick_slots, render_quick_html
from app.services.report.render import (
    apply_slots,
    dry_run_defaults,
    list_slots_in_template,
    load_template,
)
from app.services.anchor_store import ResolvedReportAnchors
from app.services.report.sanitize import sanitize_slot_output
from app.services.report.tools import ReportToolBundle
from app.services.ssr import ANCHOR_SET_VERSION

logger = logging.getLogger(__name__)

ReportMode = Literal["full", "quick"]


def _load_questions(locale: ReportLocale) -> list[dict[str, Any]]:
    data = json.loads(questions_path(locale).read_text(encoding="utf-8"))
    return list(data.get("questions") or [])


def _ssr_payload(
    *,
    classifications: list[BundleClassification],
    bundles: list[RunBundle],
    locale: ReportLocale,
    mode: ReportMode,
    ssr_temperature: float,
    classify_seconds: float,
    embed_seconds: float,
    total_seconds: float,
    resolved_anchors: ResolvedReportAnchors | None = None,
) -> dict[str, Any]:
    tone_meta = {}
    style_meta = {}
    if resolved_anchors is not None:
        tone_meta = {
            "tone_anchor_set_id": resolved_anchors["tone_id"],
            "tone_anchor_set_version": resolved_anchors["tone_version"],
        }
        style_meta = {
            "style_anchor_set_id": resolved_anchors["style_id"],
            "style_anchor_set_version": resolved_anchors["style_version"],
        }
    return {
        "mode": mode,
        "locale": locale,
        "embedding_model": settings.embedding_model,
        "anchor_set_version": ANCHOR_SET_VERSION,
        **tone_meta,
        **style_meta,
        "ssr_temperature": ssr_temperature,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "timing": {
            "classify_llm_seconds": round(classify_seconds, 3),
            "embed_seconds": round(embed_seconds, 3),
            "total_seconds": round(total_seconds, 3),
        },
        "bundles": [
            {
                "label": b.label,
                "run_id": b.run_id,
                "attempt_id": b.attempt_id,
                "tone_shares": c.tone_shares,
                "tone_mode": c.tone_mode,
                "style_avg_likes": [
                    {"style": s, "avg_likes": a} for s, a in c.style_avg_likes
                ],
                "tone_pmfs": c.tone_pmfs,
                "style_pmfs": c.style_pmfs,
                "sample_count": len(c.sample_texts),
                "sample_likes": c.sample_likes,
                "tone_rated_texts": c.tone_rated_texts,
                "style_rated_texts": c.style_rated_texts,
                "topic_mode": c.topic_mode,
                "classify_llm_seconds": round(c.classify_llm_seconds, 3),
                "embed_seconds": round(c.embed_seconds, 3),
            }
            for b, c in zip(bundles, classifications, strict=True)
        ],
    }


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
    mode: ReportMode = "full",
    ssr_temperature: float = DEFAULT_SSR_TEMPERATURE,
    resolved_anchors: ResolvedReportAnchors | None = None,
) -> tuple[Path, Path, dict[str, str], dict[str, Any]]:
    """Write report.html + slots.json (+ ssr.json). Returns paths, slots, timing meta."""
    loc = normalize_locale(locale)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    # Quick: no DeepSeek — SSR embeds reactions directly; topics from injection keywords.
    # Full: LLM topic packs + topic classify; tone/style still direct SSR (embeddings only).
    topic_mode = "injection" if mode == "quick" else "llm"
    classifications = await classify_bundles(
        bundles,
        locale=loc,
        prompts=prompts,
        topic_mode=topic_mode,
        ssr_temperature=ssr_temperature,
        tone_anchor_set=resolved_anchors["tone"] if resolved_anchors else None,
        style_anchor_set=resolved_anchors["style"] if resolved_anchors else None,
    )
    classify_llm_s = sum(c.classify_llm_seconds for c in classifications)
    embed_s = sum(c.embed_seconds for c in classifications)
    logger.info(
        "report classify timing mode=%s llm=%.2fs embed=%.2fs bundles=%d",
        mode,
        classify_llm_s,
        embed_s,
        len(bundles),
    )

    metrics = compute_report_metrics(bundles, classifications)
    total_s = time.perf_counter() - t0
    timing = {
        "classify_llm_seconds": round(classify_llm_s, 3),
        "embed_seconds": round(embed_s, 3),
        "total_seconds": round(total_s, 3),
    }

    if mode == "quick":
        slots = build_quick_slots(
            title=title,
            bundles=bundles,
            classifications=classifications,
            metrics=metrics,
            locale=loc,
            timing=timing,
        )
        html = render_quick_html(slots, locale=loc)
    else:
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
        timing["total_seconds"] = round(time.perf_counter() - t0, 3)

    html_path = out_dir / "report.html"
    slots_path = out_dir / "report.slots.json"
    ssr_path = out_dir / "report.ssr.json"
    ssr_doc = _ssr_payload(
        classifications=classifications,
        bundles=bundles,
        locale=loc,
        mode=mode,
        ssr_temperature=ssr_temperature,
        classify_seconds=classify_llm_s,
        embed_seconds=embed_s,
        total_seconds=float(timing["total_seconds"]),
        resolved_anchors=resolved_anchors,
    )
    html_path.write_text(html, encoding="utf-8")
    slots_path.write_text(
        json.dumps(
            {
                "title": title,
                "locale": loc,
                "mode": mode,
                "sources": [
                    {"run_id": b.run_id, "attempt_id": b.attempt_id, "label": b.label}
                    for b in bundles
                ],
                "slots": slots,
                "timing": ssr_doc["timing"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    ssr_path.write_text(
        json.dumps(ssr_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return html_path, slots_path, slots, ssr_doc["timing"]
