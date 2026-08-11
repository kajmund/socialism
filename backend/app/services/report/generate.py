"""Orchestrate snabbrapport generation: injection topics + SSR embeddings."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas.domain import DEFAULT_SSR_TEMPERATURE
from app.services.anchor_store import ResolvedReportAnchors
from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, classify_bundles
from app.services.report.locale import ReportLocale, normalize_locale
from app.services.report.metrics import compute_report_metrics
from app.services.report.quick import build_quick_slots, render_quick_html
from app.services.report.recommendation import build_recommendation_ssr_block
from app.services.report.sampling import SAMPLING_METHOD, SAMPLING_VERSION
from app.services.ssr import ANCHOR_SET_VERSION

logger = logging.getLogger(__name__)


def _ssr_payload(
    *,
    classifications: list[BundleClassification],
    bundles: list[RunBundle],
    locale: ReportLocale,
    ssr_temperature: float,
    classify_seconds: float,
    embed_seconds: float,
    total_seconds: float,
    resolved_anchors: ResolvedReportAnchors | None = None,
    anchor_validation: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tone_meta = {}
    style_meta = {}
    if resolved_anchors is not None:
        tone_meta = {
            "tone_anchor_set_id": resolved_anchors["tone_id"],
            "tone_anchor_set_version": resolved_anchors["tone_version"],
            "tone_pool_revision": resolved_anchors["tone_pool_revision"],
        }
        style_meta = {
            "style_anchor_set_id": resolved_anchors["style_id"],
            "style_anchor_set_version": resolved_anchors["style_version"],
            "style_pool_revision": resolved_anchors["style_pool_revision"],
        }
    return {
        "mode": "quick",
        "locale": locale,
        "embedding_model": settings.embedding_model,
        "anchor_set_version": ANCHOR_SET_VERSION,
        **tone_meta,
        **style_meta,
        "ssr_temperature": ssr_temperature,
        "anchor_validation": anchor_validation or {},
        "sampling_method": SAMPLING_METHOD,
        "sampling_version": SAMPLING_VERSION,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "timing": {
            "classify_llm_seconds": round(classify_seconds, 3),
            "embed_seconds": round(embed_seconds, 3),
            "total_seconds": round(total_seconds, 3),
        },
        "recommendation": recommendation or {},
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
                "sampling": c.sampling,
                "tone_rated_texts": c.tone_rated_texts,
                "style_rated_texts": c.style_rated_texts,
                "topic_mode": c.topic_mode,
                "classify_llm_seconds": round(c.classify_llm_seconds, 3),
                "embed_seconds": round(c.embed_seconds, 3),
            }
            for b, c in zip(bundles, classifications, strict=True)
        ],
    }


async def generate_report_html(
    bundles: list[RunBundle],
    *,
    out_dir: Path,
    title: str = "",
    locale: str = "sv",
    ssr_temperature: float = DEFAULT_SSR_TEMPERATURE,
    resolved_anchors: ResolvedReportAnchors | None = None,
    anchor_validation: dict[str, Any] | None = None,
) -> tuple[Path, Path, dict[str, str], dict[str, Any]]:
    """Write report.html + slots.json (+ ssr.json). Returns paths, slots, timing meta."""
    loc = normalize_locale(locale)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    classifications = await classify_bundles(
        bundles,
        locale=loc,
        ssr_temperature=ssr_temperature,
        tone_anchor_set=resolved_anchors["tone"] if resolved_anchors else None,
        style_anchor_set=resolved_anchors["style"] if resolved_anchors else None,
        tone_anchor_vectors=resolved_anchors["tone_vectors"] if resolved_anchors else None,
        style_anchor_vectors=resolved_anchors["style_vectors"] if resolved_anchors else None,
    )
    classify_llm_s = sum(c.classify_llm_seconds for c in classifications)
    embed_s = sum(c.embed_seconds for c in classifications)
    logger.info(
        "report classify timing mode=quick llm=%.2fs embed=%.2fs bundles=%d",
        classify_llm_s,
        embed_s,
        len(bundles),
    )

    metrics = compute_report_metrics(bundles, classifications)
    recommendation_block = build_recommendation_ssr_block(
        metrics,
        bundles,
        classifications,
        locale=loc,
    )
    total_s = time.perf_counter() - t0
    timing = {
        "classify_llm_seconds": round(classify_llm_s, 3),
        "embed_seconds": round(embed_s, 3),
        "total_seconds": round(total_s, 3),
    }

    slots = build_quick_slots(
        title=title,
        bundles=bundles,
        classifications=classifications,
        metrics=metrics,
        locale=loc,
        timing=timing,
        anchor_validation=anchor_validation,
    )
    html = render_quick_html(slots, locale=loc)
    timing["total_seconds"] = round(time.perf_counter() - t0, 3)

    html_path = out_dir / "report.html"
    slots_path = out_dir / "report.slots.json"
    ssr_path = out_dir / "report.ssr.json"
    ssr_doc = _ssr_payload(
        classifications=classifications,
        bundles=bundles,
        locale=loc,
        ssr_temperature=ssr_temperature,
        classify_seconds=classify_llm_s,
        embed_seconds=embed_s,
        total_seconds=float(timing["total_seconds"]),
        resolved_anchors=resolved_anchors,
        anchor_validation=anchor_validation,
        recommendation=recommendation_block,
    )
    html_path.write_text(html, encoding="utf-8")
    slots_path.write_text(
        json.dumps(
            {
                "title": title,
                "locale": loc,
                "mode": "quick",
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
