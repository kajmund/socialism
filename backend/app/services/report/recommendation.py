"""Rule-based snabbrapport recommendation (0–100 score, no DeepSeek)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification
from app.services.report.locale import ReportLocale
from app.services.report.metrics import BundleMetrics, ReportMetrics, pct
from app.services.report.segment_analysis import AudienceSegmentSummary
from app.services.report.segment_ssr import _critical_share, _positive_share
from app.services.report.tick_report import build_tick_stats


@dataclass
class QuickRecommendation:
    score: int
    action: str
    headline: str
    recommended_label: str | None = None
    comparison_line: str = ""
    reception_line: str = ""
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    trajectory: str = ""


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _trajectory_note(bundle: RunBundle, *, locale: ReportLocale) -> str:
    rows = build_tick_stats(bundle)
    if len(rows) < 2:
        return ""
    first = rows[0].window_engagement_score
    last = rows[-1].window_engagement_score
    if last > first * 1.1:
        return (
            "Simulated trajectory: engagement rose over the simulation period."
            if locale == "en"
            else "Simulerad utveckling: engagemang ökade under simuleringsperioden."
        )
    if last < first * 0.7:
        return (
            "Simulated trajectory: engagement cooled after the first day."
            if locale == "en"
            else "Simulerad utveckling: engagemang avkylades efter första dagen."
        )
    return (
        "Simulated trajectory: engagement stayed relatively stable across days."
        if locale == "en"
        else "Simulerad utveckling: engagemang höll sig relativt stabilt under perioden."
    )


def _bundle_score(m: BundleMetrics, *, locale: ReportLocale) -> int:
    pos = _positive_share(m.tone_shares, locale=locale)
    crit = _critical_share(m.tone_shares, locale=locale)
    inj = m.injection_likes
    eng = m.engagement_score

    score = pos * 45.0
    score += max(0.0, 0.35 - crit) * 25.0
    score += min(inj, 20) / 20.0 * 15.0
    score += min(eng, 80) / 80.0 * 15.0

    if inj <= 0:
        score = min(score, 15.0)
    elif pos >= 0.45 and crit < 0.45:
        score = max(score, 65.0)
    elif crit >= 0.45 or pos < 0.25:
        score = min(score, 45.0)

    return _clamp_score(score)


def _pick_recommended_index(metrics: ReportMetrics, *, locale: ReportLocale) -> int:
    if len(metrics.bundles) <= 1:
        return 0
    scored = [
        (
            _bundle_score(m, locale=locale),
            _positive_share(m.tone_shares, locale=locale),
            m.injection_likes,
            idx,
        )
        for idx, m in enumerate(metrics.bundles)
    ]
    scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return scored[0][3]


def _action_band(score: int, *, locale: ReportLocale) -> tuple[str, str]:
    if locale == "en":
        if score >= 75:
            return "publish", "publish"
        if score >= 55:
            return "adjust", "publish after minor adjustments"
        if score >= 35:
            return "revise", "revise before publishing"
        return "reconsider", "reconsider the message"
    if score >= 75:
        return "publicera", "publicera"
    if score >= 55:
        return "justera", "publicera efter mindre justeringar"
    if score >= 35:
        return "revidera", "justera innan publicering"
    return "ompröva", "ompröva budskapet"


def _reception_line(m: BundleMetrics, *, locale: ReportLocale) -> str:
    pos = _positive_share(m.tone_shares, locale=locale)
    crit = _critical_share(m.tone_shares, locale=locale)
    if locale == "en":
        return (
            f"Positive tone {pct(pos)}, critical {pct(crit)}, "
            f"{m.injection_likes} likes on the test message."
        )
    return (
        f"Positiv ton {pct(pos)}, kritisk ton {pct(crit)}, "
        f"{m.injection_likes} likes på testbudskapet."
    )


def _comparison_line(metrics: ReportMetrics, *, locale: ReportLocale) -> str:
    if len(metrics.bundles) < 2:
        return ""
    parts: list[str] = []
    for m in metrics.bundles:
        pos = _positive_share(m.tone_shares, locale=locale)
        if locale == "en":
            parts.append(
                f"{m.label}: positive tone {pct(pos)}, "
                f"{m.injection_likes} test-message likes"
            )
        else:
            parts.append(
                f"{m.label}: positiv ton {pct(pos)}, "
                f"{m.injection_likes} likes på testbudskap"
            )
    return " · ".join(parts)


def _headline(
    action_text: str,
    score: int,
    recommended_label: str | None,
    *,
    locale: ReportLocale,
) -> str:
    if locale == "en":
        if recommended_label:
            return (
                f"Conclusion: {recommended_label} recommended — {action_text} "
                f"(simulated support {score}/100)"
            )
        return f"Conclusion: {action_text} (simulated support {score}/100)"
    if recommended_label:
        return (
            f"Slutsats: {recommended_label} rekommenderas — {action_text} "
            f"(simulerat stöd {score}/100)"
        )
    return f"Slutsats: {action_text} (simulerat stöd {score}/100)"


def build_recommendation(
    metrics: ReportMetrics,
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    audience: list[AudienceSegmentSummary],
    *,
    locale: ReportLocale = "sv",
) -> QuickRecommendation:
    rec_idx = _pick_recommended_index(metrics, locale=locale)
    rec_metrics = metrics.bundles[rec_idx]
    rec_bundle = bundles[rec_idx] if rec_idx < len(bundles) else bundles[0]
    rec_clf = classifications[rec_idx] if rec_idx < len(classifications) else classifications[0]

    score = _bundle_score(rec_metrics, locale=locale)
    _key, action_text = _action_band(score, locale=locale)
    recommended_label = rec_metrics.label if len(metrics.bundles) > 1 else None
    headline = _headline(action_text, score, recommended_label, locale=locale)

    strengths: list[str] = []
    risks: list[str] = []
    improvements: list[str] = []

    scope = rec_metrics.label if len(metrics.bundles) > 1 else ""
    scope_prefix = f"{scope}: " if scope else ""

    if rec_metrics.injection_likes > 0:
        strengths.append(
            f"{scope_prefix}The test message received engagement in the simulation."
            if locale == "en"
            else f"{scope_prefix}Testbudskapet fick engagemang i simuleringen."
        )
    if _positive_share(rec_metrics.tone_shares, locale=locale) >= 0.35:
        strengths.append(
            f"{scope_prefix}Positive tone share "
            f"{pct(_positive_share(rec_metrics.tone_shares, locale=locale))}."
            if locale == "en"
            else f"{scope_prefix}Positiv ton "
            f"{pct(_positive_share(rec_metrics.tone_shares, locale=locale))}."
        )
    if rec_metrics.style_avg_likes:
        top_style, top_avg = max(
            ((s, a) for s, a in rec_metrics.style_avg_likes if s != "Oklassad"),
            key=lambda x: x[1],
            default=("", 0.0),
        )
        if top_avg >= 2.0 and top_style:
            strengths.append(
                f"{scope_prefix}Style «{top_style}» averaged {top_avg:.1f} likes."
                if locale == "en"
                else f"{scope_prefix}Stil «{top_style}» snittade {top_avg:.1f} likes."
            )

    if _critical_share(rec_metrics.tone_shares, locale=locale) >= 0.45:
        risks.append(
            f"{scope_prefix}Critical tone share "
            f"{pct(_critical_share(rec_metrics.tone_shares, locale=locale))}."
            if locale == "en"
            else f"{scope_prefix}Kritisk ton "
            f"{pct(_critical_share(rec_metrics.tone_shares, locale=locale))}."
        )

    from app.services.report.quick import _topic_share_by_day_half

    drift = _topic_share_by_day_half(rec_bundle, rec_clf)
    if drift["flag"]:
        risks.append(
            f"{scope_prefix}The test topic faded from the debate after day 1."
            if locale == "en"
            else f"{scope_prefix}Testämnet försvann ur debatten efter dag 1."
        )

    if len(bundles) > 1:
        from app.services.report.segment_analysis import build_audience_summaries

        rec_audience = build_audience_summaries(rec_bundle, rec_clf, locale=locale)
    else:
        rec_audience = audience

    theme_hits: set[str] = set()
    for seg in rec_audience:
        theme_hits.update(seg.themes)
        for iv in seg.interviews:
            theme_hits.update(iv.themes)

    if "finansiering" in theme_hits:
        risks.append(
            "Financing questions surfaced in segment interviews or reactions."
            if locale == "en"
            else "Finansieringsfrågan väckte skepsis eller efterfrågan i segment."
        )
        improvements.append(
            "Add a concrete financing example in the message."
            if locale == "en"
            else "Lägg till ett konkret exempel på finansiering i budskapet."
        )
    if "vaghet" in theme_hits:
        risks.append(
            "Some segments perceived vagueness in the message."
            if locale == "en"
            else "Vissa segment upplevde vaghet i budskapet."
        )
        improvements.append(
            "Tighten tone and add a specific example to reduce perceived vagueness."
            if locale == "en"
            else "Justera tonläget och lägg till ett konkret exempel för att minska upplevd vaghet."
        )

    for seg in rec_audience:
        if seg.tone and not seg.tone.too_few and seg.tone.positive_share >= 0.4:
            strengths.append(
                f"{seg.dimension_label} «{seg.label}»: positive tone ({pct(seg.tone.positive_share)})."
                if locale == "en"
                else f"{seg.dimension_label} «{seg.label}»: positiv ton ({pct(seg.tone.positive_share)})."
            )
        if seg.tone and not seg.tone.too_few and seg.tone.critical_share >= 0.5:
            risks.append(
                f"{seg.dimension_label} «{seg.label}»: critical tone ({pct(seg.tone.critical_share)})."
                if locale == "en"
                else f"{seg.dimension_label} «{seg.label}»: kritisk ton ({pct(seg.tone.critical_share)})."
            )

    trajectory = _trajectory_note(rec_bundle, locale=locale)

    if not improvements and score < 75:
        improvements.append(
            "Test a sharper concrete detail or local example in the next run."
            if locale == "en"
            else "Testa en vassare konkret detalj eller lokalt exempel i nästa körning."
        )

    return QuickRecommendation(
        score=score,
        action=action_text,
        headline=headline,
        recommended_label=recommended_label,
        comparison_line=_comparison_line(metrics, locale=locale),
        reception_line=_reception_line(rec_metrics, locale=locale),
        strengths=strengths[:4],
        risks=risks[:4],
        improvements=improvements[:3],
        trajectory=trajectory,
    )
