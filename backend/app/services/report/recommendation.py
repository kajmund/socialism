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
class AbCompareRow:
    arm: str
    positive: str
    likes: str
    is_winner: bool


@dataclass
class QuickRecommendation:
    score: int
    action: str
    recommended_arm: str | None = None
    summary: str = ""
    ab_rows: list[AbCompareRow] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _short_arm_label(label: str) -> str:
    if " — " in label:
        tail = label.rsplit(" — ", 1)[-1].strip()
        if tail:
            return tail
    return label


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


def _action_phrase(score: int, *, locale: ReportLocale) -> str:
    if locale == "en":
        if score >= 75:
            return "Ready to publish"
        if score >= 55:
            return "Publish after minor adjustments"
        if score >= 35:
            return "Revise before publishing"
        return "Reconsider the message"
    if score >= 75:
        return "Redo att publicera"
    if score >= 55:
        return "Publicera efter mindre justeringar"
    if score >= 35:
        return "Justera innan publicering"
    return "Ompröva budskapet"


def _summary(
    score: int,
    recommended_arm: str | None,
    *,
    locale: ReportLocale,
) -> str:
    if locale == "en":
        if recommended_arm:
            return (
                f"{recommended_arm} scored highest in the simulation ({score}/100) "
                f"and is the best starting point for the next iteration."
            )
        return (
            f"The message scored {score}/100 in the simulation — "
            f"use the sections below for tone, reach and target groups."
        )
    if recommended_arm:
        return (
            f"{recommended_arm} fick högst betyg i simuleringen ({score}/100) "
            f"och är bäst utgångspunkt inför nästa iteration."
        )
    return (
        f"Budskapet fick betyg {score}/100 i simuleringen — "
        f"se avsnitten nedan för ton, räckvidd och målgrupper."
    )


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
    action = _action_phrase(score, locale=locale)
    recommended_arm = (
        _short_arm_label(rec_metrics.label) if len(metrics.bundles) > 1 else None
    )

    ab_rows: list[AbCompareRow] = []
    if len(metrics.bundles) > 1:
        for idx, m in enumerate(metrics.bundles):
            ab_rows.append(
                AbCompareRow(
                    arm=_short_arm_label(m.label),
                    positive=pct(_positive_share(m.tone_shares, locale=locale)),
                    likes=str(m.injection_likes),
                    is_winner=idx == rec_idx,
                )
            )

    strengths: list[str] = []
    risks: list[str] = []
    improvements: list[str] = []

    pos = _positive_share(rec_metrics.tone_shares, locale=locale)
    crit = _critical_share(rec_metrics.tone_shares, locale=locale)

    if rec_metrics.injection_likes > 0 and pos >= 0.35:
        strengths.append(
            f"Good reception: {pct(pos)} positive tone and engagement on the test message."
            if locale == "en"
            else f"Bra mottagande: {pct(pos)} positiv ton och engagemang på testbudskapet."
        )
    elif rec_metrics.injection_likes > 0:
        strengths.append(
            "The test message drew reactions in the simulation."
            if locale == "en"
            else "Testbudskapet väckte reaktioner i simuleringen."
        )

    if crit >= 0.45:
        risks.append(
            f"Critical tone is high ({pct(crit)}) — expect pushback."
            if locale == "en"
            else f"Kritisk ton är hög ({pct(crit)}) — räkna med mothugg."
        )

    from app.services.report.quick import _topic_share_by_day_half

    if _topic_share_by_day_half(rec_bundle, rec_clf)["flag"]:
        risks.append(
            "The topic faded from the debate after day 1."
            if locale == "en"
            else "Ämnet föll bort ur debatten efter dag 1."
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
            "Financing came up in reactions or interviews."
            if locale == "en"
            else "Finansiering lyftes i reaktioner eller intervjuer."
        )
        improvements.append(
            "Add a concrete financing example."
            if locale == "en"
            else "Lägg till ett konkret finansieringsexempel."
        )
    elif "vaghet" in theme_hits:
        risks.append(
            "Some groups found the message vague."
            if locale == "en"
            else "Vissa grupper upplevde budskapet som vagt."
        )
        improvements.append(
            "Sharpen with one local, concrete detail."
            if locale == "en"
            else "Vassa till med en lokalt förankrad detalj."
        )

    for seg in rec_audience:
        if seg.tone and not seg.tone.too_few and seg.tone.positive_share >= 0.45:
            strengths.append(
                f"{seg.label} responded well ({pct(seg.tone.positive_share)} positive)."
                if locale == "en"
                else f"{seg.label} svarade väl ({pct(seg.tone.positive_share)} positiv ton)."
            )
        if seg.tone and not seg.tone.too_few and seg.tone.critical_share >= 0.5:
            risks.append(
                f"{seg.label} was sceptical ({pct(seg.tone.critical_share)} critical)."
                if locale == "en"
                else f"{seg.label} var skeptisk ({pct(seg.tone.critical_share)} kritisk ton)."
            )

    if not improvements and score < 75:
        improvements.append(
            "Test a sharper detail in the next run."
            if locale == "en"
            else "Testa en vassare detalj i nästa körning."
        )

    return QuickRecommendation(
        score=score,
        action=action,
        recommended_arm=recommended_arm,
        summary=_summary(score, recommended_arm, locale=locale),
        ab_rows=ab_rows,
        strengths=strengths[:2],
        risks=risks[:2],
        improvements=improvements[:1],
    )


def build_recommendation_ssr_block(
    metrics: ReportMetrics,
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale = "sv",
) -> dict[str, int | str | None]:
    """Snapshot for report.ssr.json — avoids parsing recommendation from HTML."""
    from app.services.report.quick import decide_verdict
    from app.services.report.segment_analysis import build_audience_summaries

    audience = [
        seg
        for b, c in zip(bundles, classifications, strict=True)
        for seg in build_audience_summaries(b, c, locale=locale)
    ]
    rec = build_recommendation(
        metrics,
        bundles,
        classifications,
        audience,
        locale=locale,
    )
    verdict = decide_verdict(metrics, bundles, locale=locale)
    return {
        "score": rec.score,
        "action": rec.action,
        "recommended_arm": rec.recommended_arm,
        "verdict_key": verdict.key,
    }
