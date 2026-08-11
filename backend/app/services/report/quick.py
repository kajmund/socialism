"""Template-based snabbrapport: SSR + deterministic metrics, no narrative LLM."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Literal

from app.config import settings
from app.services.report.bundles import RunBundle, is_ab_comparison
from app.services.report.charts import prefill_quick_chart_slots
from app.services.report.classify import BundleClassification
from app.services.report.locale import ReportLocale, display_style_label
from app.services.report.metrics import ReportMetrics, injection_likes, pct, tone_shares_sorted
from app.services.report.recommendation import build_recommendation, _short_arm_label
from app.services.report.render import REPORT_FONTS_HREF, inject_report_theme
from app.services.report.segment_analysis import build_audience_summaries
from app.services.report.sampling import SAMPLING_METHOD
from app.services.ssr import ANCHOR_SET_VERSION

# Hardcoded thresholds (not config) until calibration shows need to tweak often.
_POS_STRONG = 0.50
_POS_MIXED = 0.30
_CRIT_WEAK = 0.50
_TOPIC_DRIFT = 0.10
# Relative difference bands (A/B positive-share and style avg-likes / top score).
_DIFF_CLEAR = 0.08
_DIFF_WEAK = 0.03

_PROVOCATIVE = "Provocerande / konfronterande"

DiffBand = Literal["clear", "weak", "none"]


def _validation_issue_lines(
    validation: dict[str, Any] | None,
    *,
    locale: ReportLocale,
) -> list[str]:
    if not validation:
        return []
    lines: list[str] = []
    for key in ("tone", "style"):
        block = validation.get(key)
        if not isinstance(block, dict):
            continue
        status = str(block.get("validation_status") or "")
        if status not in ("untested", "stale", "low"):
            continue
        name = str(block.get("name") or key)
        accuracy = block.get("accuracy")
        acc_txt = ""
        if isinstance(accuracy, (int, float)):
            acc_txt = f" ({accuracy:.0%})" if locale == "en" else f" ({accuracy:.0%})"
        if locale == "en":
            kind = "Tone" if key == "tone" else "Style"
            if status == "untested":
                lines.append(f"{kind} anchors «{name}» have not been calibration-tested.")
            elif status == "stale":
                lines.append(
                    f"{kind} anchors «{name}» are stale (pool or corpus changed since last test)."
                )
            else:
                lines.append(
                    f"{kind} anchors «{name}» have low macro-accuracy{acc_txt} (<55%)."
                )
        else:
            kind = "Ton" if key == "tone" else "Stil"
            if status == "untested":
                lines.append(f"{kind}ankare «{name}» har inte kalibreringstestats.")
            elif status == "stale":
                lines.append(
                    f"{kind}ankare «{name}» är inaktuella (pool eller korpus ändrad sedan senaste test)."
                )
            else:
                lines.append(
                    f"{kind}ankare «{name}» har låg macro-träffsäkerhet{acc_txt} (<55%)."
                )
    return lines


def _sampling_tech_line(
    bundle: RunBundle,
    classification: BundleClassification,
    *,
    locale: ReportLocale,
) -> str:
    meta = classification.sampling or {}
    selected = int(meta.get("selected_count") or len(classification.sample_texts))
    eligible = int(meta.get("eligible_count") or (len(bundle.posts) + len(bundle.comments)))
    agents = int(meta.get("agent_count") or 0)
    max_per_agent = int(meta.get("max_per_agent") or 2)
    if locale == "en":
        detail = (
            f"{escape(bundle.label)}: {selected} texts stratified per agent "
            f"(max {max_per_agent}/agent) from {eligible} reactions across {agents} agents"
        )
    else:
        detail = (
            f"{escape(bundle.label)}: {selected} texter stratifierat per agent "
            f"(max {max_per_agent}/agent) ur {eligible} reaktioner från {agents} agenter"
        )
    return f"<li>{detail}</li>"


def build_anchor_validation_html(
    validation: dict[str, Any] | None,
    *,
    locale: ReportLocale,
) -> str:
    lines = _validation_issue_lines(validation, locale=locale)
    if not lines:
        return ""
    if locale == "en":
        title = "SSR anchor validation warning"
        intro = (
            "Tone and style shares below rely on anchors that are untested, stale, "
            "or below the calibration accuracy target. Treat percentages as indicative, not ground truth."
        )
    else:
        title = "Varning: SSR-ankarkalibrering"
        intro = (
            "Ton- och stilandelar nedan bygger på ankare som är otestade, inaktuella "
            "eller under kalibreringsmålet. Behandla procenten som vägledande, inte som sanning."
        )
    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    return (
        f'<div class="ag-warn ssr-validation-warning" role="note">'
        f"<p><strong>{escape(title)}</strong> — {escape(intro)}</p>"
        f"<ul>{items}</ul>"
        f"</div>"
    )


def _diff_band(diff: float) -> DiffBand:
    """Bucket a relative difference into clear / weak / no meaningful gap."""
    if diff >= _DIFF_CLEAR:
        return "clear"
    if diff >= _DIFF_WEAK:
        return "weak"
    return "none"


def _band_label(band: DiffBand, *, locale: ReportLocale) -> str:
    if locale == "en":
        if band == "clear":
            return "Clear difference"
        if band == "weak":
            return "Weak difference"
        return "No meaningful difference"
    if band == "clear":
        return "Tydlig skillnad"
    if band == "weak":
        return "Svag skillnad"
    return "Ingen meningsfull skillnad"


@dataclass
class QuickVerdict:
    key: str
    label: str
    detail: str
    positive_share: float
    critical_share: float
    threshold_note: str


def _positive_share(tone: dict[str, float], *, locale: ReportLocale) -> float:
    if locale == "en":
        return tone.get("Somewhat positive", 0.0) + tone.get("Strongly positive", 0.0)
    return tone.get("Något positiv", 0.0) + tone.get("Starkt positiv", 0.0)


def _critical_share(tone: dict[str, float], *, locale: ReportLocale) -> float:
    if locale == "en":
        return tone.get("Somewhat negative", 0.0) + tone.get("Strongly negative", 0.0)
    return tone.get("Något negativ", 0.0) + tone.get("Starkt negativ", 0.0)


def _injection_likes(bundle: RunBundle) -> int:
    return injection_likes(bundle)


def _topic_share_by_day_half(bundle: RunBundle, classification: BundleClassification) -> dict[str, Any]:
    """Approximate day-1 vs later topic share for injected topic (top pack)."""
    packs = classification.topic_packs
    if not packs or not bundle.posts:
        return {"day1": None, "later": None, "flag": False, "top_topic": None}
    top = packs[0].label
    keywords = [k.lower() for k in packs[0].keywords if k] or [top.lower()]
    n = len(bundle.posts)
    mid = max(1, n // 3)  # first third ≈ day 1 when ticks~3

    def share(posts: list[dict[str, Any]]) -> float:
        if not posts:
            return 0.0
        hits = 0
        for p in posts:
            text = str(p.get("content") or p.get("text") or "").lower()
            if any(k in text for k in keywords):
                hits += 1
        return hits / len(posts)

    day1 = share(bundle.posts[:mid])
    later = share(bundle.posts[mid:])
    flag = day1 > 0 and later < _TOPIC_DRIFT and later < day1
    return {"day1": day1, "later": later, "flag": flag, "top_topic": top}


def decide_verdict(
    metrics: ReportMetrics,
    bundles: list[RunBundle],
    *,
    locale: ReportLocale,
) -> QuickVerdict:
    tone = metrics.aggregate.tone_shares
    pos = _positive_share(tone, locale=locale)
    crit = _critical_share(tone, locale=locale)
    inj_likes = sum(_injection_likes(b) for b in bundles)

    if locale == "en":
        if inj_likes <= 0:
            return QuickVerdict(
                key="zero",
                label="Zero result",
                detail="The test message received no likes.",
                positive_share=pos,
                critical_share=crit,
                threshold_note="Triggered by 0 likes on the test message.",
            )
        if pos >= _POS_STRONG:
            return QuickVerdict(
                key="strong",
                label="Strong reception",
                detail=f"Positive tone share {pct(pos)} (≥ {pct(_POS_STRONG)}).",
                positive_share=pos,
                critical_share=crit,
                threshold_note=f"Positive ≥ {pct(_POS_STRONG)}; next band starts below that.",
            )
        if pos >= _POS_MIXED:
            return QuickVerdict(
                key="mixed",
                label="Mixed reception",
                detail=f"Positive tone share {pct(pos)} (between {pct(_POS_MIXED)} and {pct(_POS_STRONG)}).",
                positive_share=pos,
                critical_share=crit,
                threshold_note=(
                    f"Positive in [{pct(_POS_MIXED)}, {pct(_POS_STRONG)}); "
                    f"distance to strong band: {pct(_POS_STRONG - pos)}."
                ),
            )
        if crit >= _CRIT_WEAK:
            return QuickVerdict(
                key="weak",
                label="Weak reception",
                detail=f"Positive {pct(pos)} and critical {pct(crit)} (≥ {pct(_CRIT_WEAK)}).",
                positive_share=pos,
                critical_share=crit,
                threshold_note=f"Positive < {pct(_POS_MIXED)} and critical ≥ {pct(_CRIT_WEAK)}.",
            )
        return QuickVerdict(
            key="mixed",
            label="Mixed reception",
            detail=f"Positive {pct(pos)}, critical {pct(crit)} — no strong band triggered.",
            positive_share=pos,
            critical_share=crit,
            threshold_note="Default mixed when no strong/weak band matched.",
        )

    if inj_likes <= 0:
        return QuickVerdict(
            key="zero",
            label="Nollresultat",
            detail="Testbudskapet fick inga likes.",
            positive_share=pos,
            critical_share=crit,
            threshold_note="Triggas av 0 likes på testbudskapet.",
        )
    if pos >= _POS_STRONG:
        return QuickVerdict(
            key="strong",
            label="Starkt mottagande",
            detail=f"Positiv tonandel {pct(pos)} (≥ {pct(_POS_STRONG)}).",
            positive_share=pos,
            critical_share=crit,
            threshold_note=f"Positiv ≥ {pct(_POS_STRONG)}; nästa band börjar under det.",
        )
    if pos >= _POS_MIXED:
        return QuickVerdict(
            key="mixed",
            label="Blandat mottagande",
            detail=f"Positiv tonandel {pct(pos)} (mellan {pct(_POS_MIXED)} och {pct(_POS_STRONG)}).",
            positive_share=pos,
            critical_share=crit,
            threshold_note=(
                f"Positiv i [{pct(_POS_MIXED)}, {pct(_POS_STRONG)}); "
                f"avstånd till starkt band: {pct(_POS_STRONG - pos)}."
            ),
        )
    if crit >= _CRIT_WEAK:
        return QuickVerdict(
            key="weak",
            label="Svagt mottagande",
            detail=f"Positiv {pct(pos)} och kritisk {pct(crit)} (≥ {pct(_CRIT_WEAK)}).",
            positive_share=pos,
            critical_share=crit,
            threshold_note=f"Positiv < {pct(_POS_MIXED)} och kritisk ≥ {pct(_CRIT_WEAK)}.",
        )
    return QuickVerdict(
        key="mixed",
        label="Blandat mottagande",
        detail=f"Positiv {pct(pos)}, kritisk {pct(crit)} — inget starkt band triggades.",
        positive_share=pos,
        critical_share=crit,
        threshold_note="Standard blandat när varken starkt eller svagt band matchade.",
    )


def _ab_diff_html(
    metrics: ReportMetrics,
    *,
    locale: ReportLocale,
) -> str:
    if len(metrics.bundles) < 2:
        return ""
    shares = [
        (_positive_share(m.tone_shares, locale=locale), m.label) for m in metrics.bundles
    ]
    shares.sort(key=lambda x: x[0], reverse=True)
    best_pos, best_label = shares[0]
    worst_pos, worst_label = shares[-1]
    best_short = _short_arm_label(best_label)
    worst_short = _short_arm_label(worst_label)
    diff = best_pos - worst_pos
    band = _diff_band(diff)
    label = _band_label(band, locale=locale)
    if locale == "en":
        return (
            f"<p><strong>{label}</strong> — {escape(best_short)} leads "
            f"{escape(worst_short)} by {pct(diff)} positive tone "
            f"({pct(best_pos)} vs {pct(worst_pos)}).</p>"
        )
    return (
        f"<p><strong>{label}</strong> — {escape(best_short)} leder "
        f"{escape(worst_short)} med {pct(diff)} positiv ton "
        f"({pct(best_pos)} vs {pct(worst_pos)}).</p>"
    )


def _style_relative_diff(top: float, bottom: float) -> float:
    """Relative gap vs top share — same scale as A/B share diffs for bucketing."""
    if top <= 0 and bottom <= 0:
        return 0.0
    return (top - bottom) / max(top, 1e-9)


def _style_html(metrics: ReportMetrics, *, locale: ReportLocale) -> str:
    styles = metrics.aggregate.style_shares
    if not styles:
        return "<p>—</p>"
    ranked = [(s, a) for s, a in styles if s != "Oklassad"]
    if not ranked:
        ranked = list(styles)
    # Bucket top vs runner-up (not top vs last) — 41% vs 40% is noise even if
    # some other style sits at 0.
    winner_s, winner_share = ranked[0]
    second_s, second_share = ranked[1] if len(ranked) > 1 else (winner_s, winner_share)
    win = display_style_label(winner_s, locale)
    second = display_style_label(second_s, locale)
    rel = _style_relative_diff(winner_share, second_share)
    band = _diff_band(rel)
    band_lbl = _band_label(band, locale=locale)
    parts = []
    if locale == "en":
        if band == "none":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} ({pct(winner_share)} of reactions) "
                f"and {escape(second)} ({pct(second_share)}) are within noise "
                f"(gap {pct(rel)} of top; need ≥{pct(_DIFF_WEAK)} for a weak signal).</p>"
            )
        elif band == "weak":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} slightly ahead of "
                f"{escape(second)} ({pct(winner_share)} vs {pct(second_share)} of reactions).</p>"
            )
        else:
            parts.append(
                f"<p><strong>{band_lbl}</strong> — <strong>Most common style:</strong> "
                f"{escape(win)} ({pct(winner_share)} of reactions). "
                f"<strong>Next:</strong> {escape(second)} ({pct(second_share)}).</p>"
            )
        if any(s == _PROVOCATIVE and a <= 0 for s, a in ranked):
            parts.append(
                "<p>No rated reaction matched the provocative/confrontational style "
                "in this report — absence of the style, not a measured reception.</p>"
            )
    else:
        if band == "none":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} ({pct(winner_share)} av reaktionerna) "
                f"och {escape(second)} ({pct(second_share)}) ligger inom brus "
                f"(gap {pct(rel)} av toppen; ≥{pct(_DIFF_WEAK)} krävs för svag signal).</p>"
            )
        elif band == "weak":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} något före "
                f"{escape(second)} ({pct(winner_share)} mot {pct(second_share)} av reaktionerna).</p>"
            )
        else:
            parts.append(
                f"<p><strong>{band_lbl}</strong> — <strong>Vanligaste stilen:</strong> "
                f"{escape(win)} ({pct(winner_share)} av reaktionerna). "
                f"<strong>Näst:</strong> {escape(second)} ({pct(second_share)}).</p>"
            )
        if any(s == _PROVOCATIVE and a <= 0 for s, a in ranked):
            parts.append(
                "<p>Ingen klassad reaktion liknade provocerande/konfronterande stil "
                "i denna rapport — stilen saknas i underlaget, det är inte ett mätt mottagande.</p>"
            )
    return "".join(parts)


def build_quick_slots(
    *,
    title: str,
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    metrics: ReportMetrics,
    locale: ReportLocale,
    timing: dict[str, Any],
    anchor_validation: dict[str, Any] | None = None,
) -> dict[str, str]:
    drift_bits = [
        _topic_share_by_day_half(b, c)
        for b, c in zip(bundles, classifications, strict=True)
    ]
    any_drift = any(d["flag"] for d in drift_bits)
    ab = is_ab_comparison(bundles) or len(bundles) > 1

    tone_rows = "".join(
        f"<tr><td>{escape(k)}</td><td>{pct(v)}</td></tr>"
        for k, v in tone_shares_sorted(metrics.aggregate.tone_shares)
    )
    style_rows = "".join(
        f"<tr><td>{escape(display_style_label(s, locale))}</td>"
        f"<td>{pct(share)}</td></tr>"
        for s, share in metrics.aggregate.style_shares
    )

    if locale == "en":
        drift_html = (
            "<p><strong>Topic drift:</strong> the test topic fell below 10% "
            "after day 1 — it disappeared from the debate.</p>"
            if any_drift
            else "<p><strong>Topic drift:</strong> no clear drop-off after day 1.</p>"
        )
    else:
        drift_html = (
            "<p><strong>Ämnesdrift:</strong> testämnet under 10 % efter dag 1 "
            "— försvann ur debatten.</p>"
            if any_drift
            else "<p><strong>Ämnesdrift:</strong> ingen tydlig nedgång efter dag 1.</p>"
        )

    if locale == "en":
        page_title = title.strip() or "Quick report"
        eyebrow = "Quick report — automated analysis"
        tech_title = "Technical appendix"
    else:
        page_title = title.strip() or "Snabbrapport"
        eyebrow = "Snabbrapport — automatisk analys"
        tech_title = "Tekniskt stycke"

    ab_html = _ab_diff_html(metrics, locale=locale) if ab else ""
    style_html = _style_html(metrics, locale=locale)
    audience = [
        seg
        for b, c in zip(bundles, classifications, strict=True)
        for seg in build_audience_summaries(b, c, locale=locale)
    ]
    recommendation = build_recommendation(
        metrics, bundles, classifications, audience, locale=locale
    )
    chart_slots = prefill_quick_chart_slots(
        metrics,
        bundles,
        classifications,
        locale=locale,
        ab=ab,
        recommendation=recommendation,
    )

    tech_html = (
        f"<details class=\"tech\"><summary>{escape(tech_title)}</summary>"
        f"<p>{escape(decide_verdict(metrics, bundles, locale=locale).threshold_note)}</p>"
        f"<p>embedding_model={escape(settings.embedding_model)} · "
        f"anchor_set={escape(ANCHOR_SET_VERSION)} · "
        f"sampling={escape(SAMPLING_METHOD)} · "
        f"llm={timing.get('classify_llm_seconds', '—')}s · "
        f"embed={timing.get('embed_seconds', '—')}s · "
        f"total={timing.get('total_seconds', '—')}s</p>"
        f"<h4>{'Tone distribution' if locale == 'en' else 'Tonfördelning'}</h4>"
        f"<table><thead><tr><th>Level</th><th>%</th></tr></thead>"
        f"<tbody>{tone_rows}</tbody></table>"
        f"<h4>{'Style (share of reactions)' if locale == 'en' else 'Stil (andel av reaktionerna)'}</h4>"
        f"<table><thead><tr><th>Style</th><th>%</th></tr></thead>"
        f"<tbody>{style_rows}</tbody></table>"
        f"<h4>{'SSR sampling' if locale == 'en' else 'SSR-sampling'}</h4>"
        "<ul>"
        + "".join(
            _sampling_tech_line(b, c, locale=locale)
            for b, c in zip(bundles, classifications, strict=True)
        )
        + "</ul>"
        f"<h4>{'Per run sample sizes' if locale == 'en' else 'Sampelstorlek per körning'}</h4>"
        "<ul>"
        + "".join(
            f"<li>{escape(b.label)}: n={len(c.sample_texts)}, "
            f"posts={len(b.posts)}, comments={len(b.comments)}</li>"
            for b, c in zip(bundles, classifications, strict=True)
        )
        + "</ul></details>"
    )

    return {
        "page_title": page_title,
        "eyebrow": eyebrow,
        "validation_html": build_anchor_validation_html(anchor_validation, locale=locale),
        "drift_html": drift_html,
        "ab_html": ab_html or (
            f"<p>{'Single run — no A/B comparison.' if locale == 'en' else 'En körning — ingen A/B-jämförelse.'}</p>"
        ),
        "stats_html": chart_slots["stats_html"],
        "charts_html": chart_slots["charts_html"],
        "tick_html": chart_slots["tick_html"],
        "qa_html": chart_slots["qa_html"],
        "audience_html": chart_slots.get("audience_html", ""),
        "takeaway_html": chart_slots.get("takeaway_html", ""),
        "recommendation_html": chart_slots.get("recommendation_html", ""),
        "style_html": style_html,
        "tech_html": tech_html,
        "meta_runs": ", ".join(b.label for b in bundles),
    }


def render_quick_html(slots: dict[str, str], *, locale: ReportLocale) -> str:
    lang = "en" if locale == "en" else "sv"
    if locale == "en":
        h_stats = "Static statistics"
        h_charts = "Charts"
        h_ticks = "Day by day"
        h_qa = "Questions & answers"
        h_audience = "Target groups"
        h_takeaway = "Audience summary"
        h_drift = "Topic drift"
        h_ab = "A/B comparison"
        h_style = "Style impact"
    else:
        h_stats = "Statistik"
        h_charts = "Diagram"
        h_ticks = "Dag för dag"
        h_qa = "Frågor och svar"
        h_audience = "Målgruppsanalys"
        h_takeaway = "Sammanfattning målgrupper"
        h_drift = "Ämnesdrift"
        h_ab = "A/B-jämförelse"
        h_style = "Stilgenomslag"
    html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{escape(slots.get("page_title", "Snabbrapport"))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="{REPORT_FONTS_HREF}" rel="stylesheet"/>
<style>
/*@@REPORT_THEME_CSS@@*/
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">{escape(slots.get("eyebrow", ""))}</div>
  <h1>{escape(slots.get("page_title", ""))}</h1>
  {slots.get("validation_html", "")}
  {slots.get("recommendation_html", "")}
  <section>
    <h3>{h_stats}</h3>
    {slots.get("stats_html", "")}
  </section>
  <section>
    <h3>{h_charts}</h3>
    {slots.get("charts_html", "")}
  </section>
  <section>
    <h3>{h_ticks}</h3>
    {slots.get("tick_html", "")}
  </section>
  <section>
    <h3>{h_qa}</h3>
    {slots.get("qa_html", "")}
  </section>
  <section>
    <h3>{h_takeaway}</h3>
    {slots.get("takeaway_html", "")}
  </section>
  <section>
    <h3>{h_audience}</h3>
    {slots.get("audience_html", "")}
  </section>
  <section>
    <h3>{h_ab}</h3>
    {slots.get("ab_html", "")}
  </section>
  <section>
    <h3>{h_drift}</h3>
    {slots.get("drift_html", "")}
  </section>
  <section>
    <h3>{h_style}</h3>
    {slots.get("style_html", "")}
  </section>
  {slots.get("tech_html", "")}
  <p class="meta">{escape(slots.get("meta_runs", ""))}</p>
</div>
</body>
</html>
"""
    return inject_report_theme(html)
