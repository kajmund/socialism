"""Rule-based snabbrapport recommendation (0–100 score, no DeepSeek)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification
from app.services.report.locale import ReportLocale
from app.services.report.metrics import BundleMetrics, ReportMetrics, pct
from app.services.report.segment_analysis import AudienceSegmentSummary
from app.services.report.segment_ssr import _critical_share, _positive_share
from app.services.report.thresholds import ReportThresholds, default_report_thresholds


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


def _bundle_score(
    m: BundleMetrics,
    *,
    locale: ReportLocale,
    thresholds: ReportThresholds,
) -> int:
    rec = thresholds.recommendation
    w = rec.score_weights
    caps = rec.score_caps
    triggers = rec.score_triggers

    pos = _positive_share(m.tone_shares, locale=locale)
    crit = _critical_share(m.tone_shares, locale=locale)
    inj = m.injection_likes
    eng = m.engagement_score

    score = pos * w.positive
    score += max(0.0, triggers.crit_baseline - crit) * w.critical_headroom
    score += min(inj, caps.injection_likes_cap) / caps.injection_likes_cap * w.injection_likes
    score += min(eng, caps.engagement_cap) / caps.engagement_cap * w.engagement

    if inj <= 0:
        score = min(score, caps.zero_likes_max)
    elif pos >= triggers.strong_pos and crit < triggers.strong_crit_max:
        score = max(score, caps.strong_floor)
    elif crit >= triggers.strong_crit_max or pos < triggers.weak_pos_max:
        score = min(score, caps.weak_ceiling)

    return _clamp_score(score)


def _pick_recommended_index(
    metrics: ReportMetrics,
    *,
    locale: ReportLocale,
    thresholds: ReportThresholds,
) -> int:
    if len(metrics.bundles) <= 1:
        return 0
    scored = [
        (
            _bundle_score(m, locale=locale, thresholds=thresholds),
            _positive_share(m.tone_shares, locale=locale),
            m.injection_likes,
            idx,
        )
        for idx, m in enumerate(metrics.bundles)
    ]
    scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return scored[0][3]


def _action_phrase(
    score: int,
    *,
    locale: ReportLocale,
    thresholds: ReportThresholds,
) -> str:
    bands = thresholds.recommendation.action_bands
    if locale == "en":
        if score >= bands.ready:
            return "Ready to publish"
        if score >= bands.minor_adjust:
            return "Publish after minor adjustments"
        if score >= bands.revise:
            return "Revise before publishing"
        return "Reconsider the message"
    if score >= bands.ready:
        return "Redo att publicera"
    if score >= bands.minor_adjust:
        return "Publicera efter mindre justeringar"
    if score >= bands.revise:
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
    thresholds: ReportThresholds | None = None,
) -> QuickRecommendation:
    t = thresholds if thresholds is not None else default_report_thresholds()
    narrative = t.recommendation.narrative
    action_bands = t.recommendation.action_bands

    rec_idx = _pick_recommended_index(metrics, locale=locale, thresholds=t)
    rec_metrics = metrics.bundles[rec_idx]
    rec_bundle = bundles[rec_idx] if rec_idx < len(bundles) else bundles[0]
    rec_clf = classifications[rec_idx] if rec_idx < len(classifications) else classifications[0]

    score = _bundle_score(rec_metrics, locale=locale, thresholds=t)
    action = _action_phrase(score, locale=locale, thresholds=t)
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

    if rec_metrics.injection_likes > 0 and pos >= narrative.good_reception_pos:
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

    if crit >= narrative.high_crit:
        risks.append(
            f"Critical tone is high ({pct(crit)}) — expect pushback."
            if locale == "en"
            else f"Kritisk ton är hög ({pct(crit)}) — räkna med mothugg."
        )

    from app.services.report.quick import _topic_share_by_day_half

    if _topic_share_by_day_half(rec_bundle, rec_clf, t)["flag"]:
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
        if seg.tone and not seg.tone.too_few and seg.tone.positive_share >= narrative.segment_pos:
            strengths.append(
                f"{seg.label} responded well ({pct(seg.tone.positive_share)} positive)."
                if locale == "en"
                else f"{seg.label} svarade väl ({pct(seg.tone.positive_share)} positiv ton)."
            )
        if seg.tone and not seg.tone.too_few and seg.tone.critical_share >= narrative.segment_crit:
            risks.append(
                f"{seg.label} was sceptical ({pct(seg.tone.critical_share)} critical)."
                if locale == "en"
                else f"{seg.label} var skeptisk ({pct(seg.tone.critical_share)} kritisk ton)."
            )

    if not improvements and score < action_bands.ready:
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
