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
from app.services.report.metrics import ReportMetrics, injection_likes, pct
from app.services.report.recommendation import build_recommendation
from app.services.report.segment_analysis import build_audience_summaries
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
    diff = best_pos - worst_pos
    band = _diff_band(diff)
    label = _band_label(band, locale=locale)
    if locale == "en":
        return (
            f"<p><strong>{label}</strong> — {escape(best_label)} leads "
            f"{escape(worst_label)} by {pct(diff)} positive tone "
            f"({pct(best_pos)} vs {pct(worst_pos)}).</p>"
        )
    return (
        f"<p><strong>{label}</strong> — {escape(best_label)} leder "
        f"{escape(worst_label)} med {pct(diff)} positiv ton "
        f"({pct(best_pos)} vs {pct(worst_pos)}).</p>"
    )


def _style_relative_diff(top: float, bottom: float) -> float:
    """Relative gap vs top score — same scale as A/B share diffs for bucketing."""
    if top <= 0 and bottom <= 0:
        return 0.0
    return (top - bottom) / max(top, 1e-9)


def _style_html(metrics: ReportMetrics, *, locale: ReportLocale) -> str:
    styles = metrics.aggregate.style_avg_likes
    if not styles:
        return "<p>—</p>"
    ranked = [(s, a) for s, a in styles if s != "Oklassad"]
    if not ranked:
        ranked = list(styles)
    # Bucket top vs runner-up (not top vs last) — 9.0 vs 8.9 is noise even if
    # some other style sits at 0.
    winner_s, winner_a = ranked[0]
    second_s, second_a = ranked[1] if len(ranked) > 1 else (winner_s, winner_a)
    win = display_style_label(winner_s, locale)
    second = display_style_label(second_s, locale)
    rel = _style_relative_diff(winner_a, second_a)
    band = _diff_band(rel)
    band_lbl = _band_label(band, locale=locale)
    parts = []
    if locale == "en":
        if band == "none":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} ({winner_a:.1f} avg likes) "
                f"and {escape(second)} ({second_a:.1f}) are within noise "
                f"(gap {rel:.0%} of top; need ≥{_DIFF_WEAK:.0%} for a weak signal).</p>"
            )
        elif band == "weak":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} slightly ahead of "
                f"{escape(second)} ({winner_a:.1f} vs {second_a:.1f} avg likes).</p>"
            )
        else:
            parts.append(
                f"<p><strong>{band_lbl}</strong> — <strong>Winning style:</strong> "
                f"{escape(win)} ({winner_a:.1f} avg likes). "
                f"<strong>Next:</strong> {escape(second)} ({second_a:.1f}).</p>"
            )
        if any(s == _PROVOCATIVE and a <= 0 for s, a in ranked):
            parts.append(
                "<p>Provocative/confrontational style got 0 avg likes "
                "(confirmed pilot pattern).</p>"
            )
    else:
        if band == "none":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} ({winner_a:.1f} snittlikes) "
                f"och {escape(second)} ({second_a:.1f}) ligger inom brus "
                f"(gap {rel:.0%} av toppen; ≥{_DIFF_WEAK:.0%} krävs för svag signal).</p>"
            )
        elif band == "weak":
            parts.append(
                f"<p><strong>{band_lbl}</strong> — {escape(win)} något före "
                f"{escape(second)} ({winner_a:.1f} vs {second_a:.1f} snittlikes).</p>"
            )
        else:
            parts.append(
                f"<p><strong>{band_lbl}</strong> — <strong>Vinnande stil:</strong> "
                f"{escape(win)} ({winner_a:.1f} snittlikes). "
                f"<strong>Näst:</strong> {escape(second)} ({second_a:.1f}).</p>"
            )
        if any(s == _PROVOCATIVE and a <= 0 for s, a in ranked):
            parts.append(
                "<p>Provocerande/konfronterande stil fick 0 snittlikes "
                "(bekräftat mönster i pilotdata).</p>"
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
) -> dict[str, str]:
    verdict = decide_verdict(metrics, bundles, locale=locale)
    drift_bits = [
        _topic_share_by_day_half(b, c)
        for b, c in zip(bundles, classifications, strict=True)
    ]
    any_drift = any(d["flag"] for d in drift_bits)
    ab = is_ab_comparison(bundles) or len(bundles) > 1

    tone_rows = "".join(
        f"<tr><td>{escape(k)}</td><td>{pct(v)}</td></tr>"
        for k, v in metrics.aggregate.tone_shares.items()
    )
    style_rows = "".join(
        f"<tr><td>{escape(display_style_label(s, locale))}</td>"
        f"<td>{a:.2f}</td></tr>"
        for s, a in metrics.aggregate.style_avg_likes
    )

    if locale == "en":
        drift_html = (
            "<p><strong>Topic drift:</strong> the test topic fell below 10% "
            "after day 1 — it disappeared from the debate.</p>"
            if any_drift
            else "<p><strong>Topic drift:</strong> no clear drop-off after day 1.</p>"
        )
        page_title = title.strip() or "Quick report"
        eyebrow = "Quick report — automated analysis"
        tech_title = "Technical appendix"
    else:
        drift_html = (
            "<p><strong>Ämnesdrift:</strong> testämnet under 10 % efter dag 1 "
            "— försvann ur debatten.</p>"
            if any_drift
            else "<p><strong>Ämnesdrift:</strong> ingen tydlig nedgång efter dag 1.</p>"
        )
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
        f"<p>{escape(verdict.threshold_note)}</p>"
        f"<p>embedding_model={escape(settings.embedding_model)} · "
        f"anchor_set={escape(ANCHOR_SET_VERSION)} · "
        f"llm={timing.get('classify_llm_seconds', '—')}s · "
        f"embed={timing.get('embed_seconds', '—')}s · "
        f"total={timing.get('total_seconds', '—')}s</p>"
        f"<h4>{'Tone distribution' if locale == 'en' else 'Tonfördelning'}</h4>"
        f"<table><thead><tr><th>Level</th><th>%</th></tr></thead>"
        f"<tbody>{tone_rows}</tbody></table>"
        f"<h4>{'Style avg likes' if locale == 'en' else 'Stil snittlikes'}</h4>"
        f"<table><thead><tr><th>Style</th><th>avg</th></tr></thead>"
        f"<tbody>{style_rows}</tbody></table>"
        f"<h4>{'Per run sample sizes' if locale == 'en' else 'Sampelstorlek per körning'}</h4>"
        "<ul>"
        + "".join(
            f"<li>{escape(b.label)}: n={len(c.sample_texts)}, "
            f"posts={len(b.posts)}, comments={len(b.comments)}</li>"
            for b, c in zip(bundles, classifications, strict=True)
        )
        + "</ul></details>"
    )

    verdict_class = {
        "strong": "v-strong",
        "mixed": "v-mixed",
        "weak": "v-weak",
        "zero": "v-zero",
    }.get(verdict.key, "v-mixed")

    return {
        "page_title": page_title,
        "eyebrow": eyebrow,
        "verdict_class": verdict_class,
        "verdict_label": verdict.label,
        "verdict_detail": verdict.detail,
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
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8"/>
<title>{escape(slots.get("page_title", "Snabbrapport"))}</title>
<style>
body{{font-family:Georgia,serif;background:#F7F3EA;color:#1A1814;margin:0;padding:2rem;}}
.wrap{{max-width:960px;margin:0 auto;}}
.eyebrow{{font-size:.85rem;letter-spacing:.04em;text-transform:uppercase;color:#6B6253;}}
h1{{font-size:1.75rem;margin:.35rem 0 1.25rem;}}
.verdict{{border:1px solid #D8CFC0;padding:1.25rem 1.5rem;margin:1rem 0;background:#FFFCF6;}}
.v-strong{{border-left:6px solid #5F7A4C;}}
.v-mixed{{border-left:6px solid #D8A14A;}}
.v-weak{{border-left:6px solid #B0563F;}}
.v-zero{{border-left:6px solid #6B6253;}}
.verdict h2{{margin:0 0 .35rem;font-size:1.35rem;}}
section{{margin:1.75rem 0;}}
section h3{{font-size:1.05rem;margin:0 0 .5rem;border-bottom:1px solid #D8CFC0;padding-bottom:.35rem;}}
.tech{{margin-top:2.5rem;font-size:.9rem;color:#3A342C;}}
.tech summary{{cursor:pointer;font-weight:600;}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1rem;}}
td,th{{border-bottom:1px solid #E5DDD0;padding:.35rem .5rem;text-align:left;font-size:.85rem;}}
.meta{{color:#6B6253;font-size:.9rem;margin-top:2rem;}}
.chart-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:.75rem;}}
.chart-card{{background:#FFFCF6;border:1px solid #D8CFC0;border-radius:8px;padding:14px 16px;}}
.chart-card.wide{{grid-column:1/-1;}}
.chart-card h4{{font-size:.95rem;font-weight:700;margin:0 0 4px;}}
.chart-sub{{font-size:.8rem;color:#6B6253;margin-bottom:10px;}}
.donut-wrap{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;}}
.donut{{width:88px;height:88px;border-radius:50%;position:relative;flex-shrink:0;}}
.donut-hole{{position:absolute;inset:18%;background:#FFFCF6;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:700;text-transform:uppercase;color:#6B6253;}}
.legend{{font-size:.75rem;line-height:1.35;}}
.leg-item{{display:flex;align-items:center;gap:6px;margin-bottom:3px;}}
.leg-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0;}}
.hbar-chart{{display:flex;flex-direction:column;gap:8px;}}
.hbar-row{{display:flex;align-items:center;gap:8px;font-size:.8rem;}}
.hbar-lbl{{flex:0 0 120px;line-height:1.2;}}
.hbar-track{{flex:1;height:22px;background:#EDE6DA;border-radius:4px;overflow:hidden;}}
.hbar-fill{{height:100%;display:flex;align-items:center;padding:0 6px;font-size:.7rem;font-weight:700;color:#fff;min-width:2px;}}
.hbar-val{{min-width:28px;text-align:right;font-weight:700;}}
.stats-table th{{white-space:nowrap;}}
.ab-compare{{display:flex;flex-direction:column;gap:12px;}}
.ab-metric-label{{font-size:.82rem;font-weight:700;margin-bottom:4px;color:#3A342C;}}
.ab-bar-line{{display:grid;grid-template-columns:minmax(80px,1fr) 1fr auto;gap:8px;align-items:center;margin-bottom:4px;font-size:.78rem;}}
.ab-arm{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#6B6253;}}
.ab-track{{height:18px;background:#EDE6DA;border-radius:4px;overflow:hidden;}}
.ab-fill{{height:100%;border-radius:4px;min-width:2px;}}
.ab-val{{font-weight:700;min-width:32px;text-align:right;}}
.ab-tone-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;}}
.ab-tone-head{{font-weight:700;font-size:.85rem;margin-bottom:6px;}}
.pop-compare{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:8px;}}
.pop-card{{border:1px solid #D8CFC0;border-radius:8px;overflow:hidden;background:#fff;}}
.pop-head{{background:#EDE6DA;padding:8px 10px;font-weight:700;font-size:.85rem;}}
.pop-head small{{display:block;font-weight:400;color:#6B6253;font-size:.75rem;}}
.pop-body{{padding:8px 10px;font-size:.8rem;}}
.pop-row{{display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px solid #F0EBE2;}}
.pop-row-l{{color:#6B6253;}}
.pop-row-v{{font-weight:700;}}
.agents-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;}}
.agent-card{{border:1px solid #D8CFC0;border-radius:8px;padding:10px;font-size:.8rem;background:#fff;}}
.ag-name{{font-weight:700;}}
.ag-title{{color:#6B6253;font-size:.75rem;margin-bottom:6px;}}
.ag-scores{{display:flex;gap:8px;}}
.ag-score-v{{font-weight:700;font-size:1rem;}}
.ag-score-l{{font-size:.65rem;color:#6B6253;}}
.ag-quote{{margin-top:6px;font-style:italic;color:#3A342C;font-size:.75rem;}}
.tick-timeline{{display:flex;flex-direction:column;gap:20px;}}
.tick-bundle h4{{font-size:.95rem;margin:0 0 8px;}}
.tick-spark{{margin-bottom:10px;}}
.tick-spark-title{{font-size:.78rem;color:#6B6253;margin-bottom:6px;}}
.tick-bars{{display:flex;align-items:flex-end;gap:6px;height:72px;padding:4px 0;border-bottom:1px solid #E5DDD0;}}
.tick-bar-col{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;min-width:28px;}}
.tick-bar{{width:100%;max-width:36px;background:#1E3A55;border-radius:4px 4px 0 0;min-height:4px;}}
.tick-bar-col.tick-silent .tick-bar{{background:#6B6253;opacity:.55;}}
.tick-bar-lbl{{font-size:.65rem;color:#6B6253;margin-top:4px;}}
.tick-table td{{font-size:.78rem;vertical-align:top;}}
.qa-section{{display:flex;flex-direction:column;gap:16px;}}
.qa-bundle h4{{font-size:.95rem;margin:0 0 8px;}}
.qa-tick h5{{font-size:.85rem;margin:0 0 6px;color:#3A342C;}}
.qa-card{{border:1px solid #D8CFC0;border-radius:8px;padding:10px 12px;margin-bottom:8px;background:#FFFCF6;}}
.qa-agent{{font-weight:700;font-size:.85rem;margin-bottom:2px;}}
.qa-profile{{font-size:.75rem;color:#6B6253;margin-bottom:6px;line-height:1.35;}}
.qa-q,.qa-a{{font-size:.82rem;line-height:1.4;margin-top:4px;}}
.recommendation-block{{border:1px solid #D8CFC0;border-radius:8px;padding:12px 14px;margin:0 0 1rem;background:#FFFCF6;}}
.rec-headline{{font-size:1.05rem;margin:0 0 .5rem;}}
.rec-sub{{margin:.35rem 0 .15rem;font-size:.85rem;}}
.rec-list{{margin:0 0 .5rem 1.1rem;font-size:.82rem;line-height:1.4;}}
.rec-traj{{font-size:.82rem;color:#3A342C;margin:.35rem 0 0;}}
.audience-section{{display:flex;flex-direction:column;gap:24px;}}
.aud-bundle-title{{font-size:1rem;margin:0 0 12px;border-bottom:1px solid #D8CFC0;padding-bottom:6px;}}
.aud-reports{{display:flex;flex-direction:column;gap:20px;}}
.aud-report{{border:1px solid #D8CFC0;border-radius:10px;padding:16px 18px;background:#FFFCF6;}}
.aud-report-head{{margin:0 0 8px;}}
.aud-report-head h4{{display:inline;font-size:1.05rem;margin:0;}}
.aud-dim{{color:#6B6253;font-size:.78rem;display:block;margin-bottom:2px;}}
.aud-narrative{{font-size:.88rem;line-height:1.5;color:#3A342C;margin:0 0 12px;}}
.aud-kpi-row{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px;}}
.aud-kpi{{flex:1;min-width:72px;border:1px solid #E5DDD0;border-radius:6px;padding:8px 10px;background:#fff;text-align:center;}}
.aud-kpi strong{{display:block;font-size:1.1rem;color:#1E3A55;}}
.aud-kpi span{{font-size:.68rem;color:#6B6253;}}
.aud-chart-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:12px;}}
.aud-chart-card{{border:1px solid #E5DDD0;border-radius:8px;padding:10px 12px;background:#fff;}}
.aud-chart-title{{font-size:.78rem;font-weight:700;color:#3A342C;margin-bottom:8px;}}
.aud-eng-chart{{display:flex;flex-direction:column;gap:6px;}}
.aud-eng-row{{display:grid;grid-template-columns:88px 1fr 32px;gap:6px;align-items:center;font-size:.75rem;}}
.aud-eng-lbl{{color:#6B6253;line-height:1.2;}}
.aud-eng-track{{height:16px;background:#EDE6DA;border-radius:4px;overflow:hidden;}}
.aud-eng-fill{{height:100%;border-radius:4px;min-width:2px;}}
.aud-eng-val{{font-weight:700;text-align:right;}}
.aud-samples{{margin-bottom:12px;}}
.aud-quote{{margin:6px 0 0;padding:8px 10px;border-left:3px solid #D8CFC0;background:#fff;font-size:.78rem;font-style:italic;color:#3A342C;}}
.aud-qa-block{{margin-top:8px;}}
.aud-qa-card{{border:1px solid #E5DDD0;border-radius:8px;padding:10px 12px;margin-top:8px;background:#fff;}}
.aud-qa-meta{{font-size:.75rem;font-weight:700;color:#6B6253;margin-bottom:4px;}}
.aud-qa-q,.aud-qa-a{{font-size:.82rem;line-height:1.45;margin-top:4px;}}
.audience-takeaway p{{font-size:.88rem;line-height:1.45;margin:0 0 .65rem;color:#3A342C;}}
.audience-takeaway p:last-child{{margin-bottom:0;}}
.aud-ab-legend{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:16px;padding:10px 12px;border:1px solid #D8CFC0;border-radius:8px;background:#FFFCF6;}}
.aud-ab-legend-lbl{{font-size:.78rem;font-weight:700;color:#3A342C;}}
.aud-ab-chip{{font-size:.78rem;padding:4px 10px;border-radius:999px;background:#1E3A55;color:#fff;font-weight:600;}}
.aud-ab-diff{{font-size:.85rem;font-weight:600;color:#1E3A55;margin:0 0 12px;padding:8px 10px;border-radius:6px;background:#EDE6DA;line-height:1.4;}}
.aud-arm-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;}}
.aud-arm-panel{{border:1px solid #E5DDD0;border-radius:8px;padding:12px 14px;background:#fff;}}
.aud-arm-panel.aud-arm-empty{{background:#FAF7F2;}}
.aud-arm-head{{font-size:.88rem;font-weight:700;color:#1E3A55;margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid #E5DDD0;}}
.aud-compare .aud-narrative{{font-size:.82rem;}}
.muted{{color:#6B6253;font-size:.9rem;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">{escape(slots.get("eyebrow", ""))}</div>
  <h1>{escape(slots.get("page_title", ""))}</h1>
  {slots.get("recommendation_html", "")}
  <div class="verdict {escape(slots.get("verdict_class", "v-mixed"))}">
    <h2>{escape(slots.get("verdict_label", ""))}</h2>
    <p>{escape(slots.get("verdict_detail", ""))}</p>
  </div>
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
