"""Rule-based snabbrapport recommendation (0–100 score, no DeepSeek)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification
from app.services.report.locale import ReportLocale
from app.services.report.metrics import ReportMetrics, injection_likes, pct
from app.services.report.segment_analysis import AudienceSegmentSummary, detect_themes
from app.services.report.segment_ssr import _critical_share, _positive_share
from app.services.report.tick_report import build_tick_stats


@dataclass
class QuickRecommendation:
    score: int
    action: str
    headline: str
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
            "Simulated trajectory: engagement rose over the tick window."
            if locale == "en"
            else "Simulerad utveckling: engagemang ökade över tick-fönstret."
        )
    if last < first * 0.7:
        return (
            "Simulated trajectory: engagement cooled after the initial tick."
            if locale == "en"
            else "Simulerad utveckling: engagemang avkylades efter första ticken."
        )
    return (
        "Simulated trajectory: engagement stayed relatively stable across ticks."
        if locale == "en"
        else "Simulerad utveckling: engagemang höll sig relativt stabilt över tickarna."
    )


def _composite_score(
    metrics: ReportMetrics,
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale,
) -> int:
    from app.services.report.quick import decide_verdict

    verdict = decide_verdict(metrics, bundles, locale=locale)
    pos = verdict.positive_share
    crit = verdict.critical_share
    inj = sum(injection_likes(b) for b in bundles)
    eng = metrics.aggregate.engagement_score

    score = pos * 45.0
    score += max(0.0, 0.35 - crit) * 25.0
    score += min(inj, 20) / 20.0 * 15.0
    score += min(eng, 80) / 80.0 * 15.0

    if verdict.key == "zero":
        score = min(score, 15.0)
    elif verdict.key == "weak":
        score = min(score, 45.0)
    elif verdict.key == "strong":
        score = max(score, 65.0)

    return _clamp_score(score)


def _action_band(score: int, *, locale: ReportLocale) -> tuple[str, str]:
    if locale == "en":
        if score >= 75:
            return "publish", "Recommendation: publish."
        if score >= 55:
            return "adjust", "Recommendation: publish after minor adjustments."
        if score >= 35:
            return "revise", "Recommendation: revise before publishing."
        return "reconsider", "Recommendation: reconsider the message."
    if score >= 75:
        return "publicera", "Rekommendation: publicera."
    if score >= 55:
        return "justera", "Rekommendation: publicera efter mindre justeringar."
    if score >= 35:
        return "revidera", "Rekommendation: justera innan publicering."
    return "ompröva", "Rekommendation: ompröva budskapet."


def build_recommendation(
    metrics: ReportMetrics,
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    audience: list[AudienceSegmentSummary],
    *,
    locale: ReportLocale = "sv",
) -> QuickRecommendation:
    score = _composite_score(metrics, bundles, classifications, locale=locale)
    _key, action = _action_band(score, locale=locale)
    if locale == "en":
        headline = f"Simulated support {score}/100 — {action}"
    else:
        headline = f"Simulerat stöd {score}/100 — {action}"

    strengths: list[str] = []
    risks: list[str] = []
    improvements: list[str] = []

    if metrics.aggregate.injection_likes > 0:
        strengths.append(
            "Injected message received engagement in the simulation."
            if locale == "en"
            else "Injicerat budskap fick engagemang i simuleringen."
        )
    if _positive_share(metrics.aggregate.tone_shares, locale=locale) >= 0.35:
        strengths.append(
            f"Positive SSR tone share {pct(_positive_share(metrics.aggregate.tone_shares, locale=locale))}."
            if locale == "en"
            else f"Positiv SSR-ton {pct(_positive_share(metrics.aggregate.tone_shares, locale=locale))}."
        )
    if metrics.aggregate.style_avg_likes:
        top_style, top_avg = max(
            ((s, a) for s, a in metrics.aggregate.style_avg_likes if s != "Oklassad"),
            key=lambda x: x[1],
            default=("", 0.0),
        )
        if top_avg >= 2.0 and top_style:
            strengths.append(
                f"Style «{top_style}» averaged {top_avg:.1f} likes."
                if locale == "en"
                else f"Stil «{top_style}» snittade {top_avg:.1f} likes."
            )

    if _critical_share(metrics.aggregate.tone_shares, locale=locale) >= 0.45:
        risks.append(
            f"Critical SSR tone share {pct(_critical_share(metrics.aggregate.tone_shares, locale=locale))}."
            if locale == "en"
            else f"Kritisk SSR-ton {pct(_critical_share(metrics.aggregate.tone_shares, locale=locale))}."
        )

    any_drift = False
    if bundles and classifications:
        from app.services.report.quick import _topic_share_by_day_half

        any_drift = any(
            _topic_share_by_day_half(b, c)["flag"]
            for b, c in zip(bundles, classifications, strict=True)
        )
    if any_drift:
        risks.append(
            "Injected topic faded from the debate after day 1."
            if locale == "en"
            else "Injicerat ämne försvann ur debatten efter dag 1."
        )

    theme_hits: set[str] = set()
    for seg in audience:
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

    for seg in audience:
        if seg.tone and not seg.tone.too_few and seg.tone.positive_share >= 0.4:
            strengths.append(
                f"{seg.dimension_label} «{seg.label}»: positive ({pct(seg.tone.positive_share)} SSR)."
                if locale == "en"
                else f"{seg.dimension_label} «{seg.label}»: positiva ({pct(seg.tone.positive_share)} SSR)."
            )
        if seg.tone and not seg.tone.too_few and seg.tone.critical_share >= 0.5:
            risks.append(
                f"{seg.dimension_label} «{seg.label}»: critical tone ({pct(seg.tone.critical_share)})."
                if locale == "en"
                else f"{seg.dimension_label} «{seg.label}»: kritisk ton ({pct(seg.tone.critical_share)})."
            )

    trajectory = ""
    if bundles:
        trajectory = _trajectory_note(bundles[0], locale=locale)

    if not improvements and score < 75:
        improvements.append(
            "Test a sharper concrete detail or local example in the next run."
            if locale == "en"
            else "Testa en vassare konkret detalj eller lokalt exempel i nästa körning."
        )

    return QuickRecommendation(
        score=score,
        action=action,
        headline=headline,
        strengths=strengths[:4],
        risks=risks[:4],
        improvements=improvements[:3],
        trajectory=trajectory,
    )
