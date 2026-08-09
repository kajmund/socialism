"""Målgruppsanalys: bio segments × tone + interview themes (rule-based, no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, _keywords_from_text
from app.services.report.locale import ReportLocale
from app.services.report.metrics import pct
from app.services.report.persona_bio import (
    build_agent_bio_by_index,
    persona_profile_line,
    segment_value,
)
from app.services.report.audience_takeaway import short_bundle_arm_label
from app.services.report.segment_ssr import (
    SegmentToneRow,
    build_segment_tone_rows,
    segment_dimension_label,
)
from app.services.report.tick_report import extract_interview_qa

_THEME_PATTERNS: dict[str, tuple[str, ...]] = {
    "finansiering": (
        r"finansier",
        r"budget",
        r"kostnad",
        r"betala",
        r"skatte",
        r"financing",
        r"budget",
    ),
    "trygghet": (r"trygg", r"säker", r"safety", r"security"),
    "vaghet": (r"\bvag\b", r"oviss", r"unclear", r"vague", r"uncertain"),
    "konkret": (r"konkret", r"specifik", r"exempel", r"concrete", r"specific"),
}

_THEME_LABELS_SV: dict[str, str] = {
    "finansiering": "Finansiering",
    "trygghet": "Trygghet",
    "vaghet": "Vaghet",
    "konkret": "Konkret innehåll",
}

_THEME_LABELS_EN: dict[str, str] = {
    "finansiering": "Financing",
    "trygghet": "Safety",
    "vaghet": "Vagueness",
    "konkret": "Concrete detail",
}

MAX_INTERVIEWS_SHOWN = 8
_INSIGHT_THEMES = frozenset({"finansiering", "vaghet", "konkret"})

_DIMENSION_ORDER = ("livssituation", "ort", "lutning")


@dataclass
class SegmentInterviewSnippet:
    agent_name: str
    question: str
    answer: str
    tick_index: int = 0
    day: int = 1
    themes: list[str] = field(default_factory=list)
    relevance_score: int = 0
    profile_line: str = ""


@dataclass
class AudienceSegmentSummary:
    dimension: str
    dimension_label: str
    label: str
    tone: SegmentToneRow | None
    interviews: list[SegmentInterviewSnippet] = field(default_factory=list)
    interview_total: int = 0
    themes: list[str] = field(default_factory=list)
    theme_counts: dict[str, int] = field(default_factory=dict)
    narrative: str = ""


@dataclass
class SegmentArmSummary:
    arm_label: str
    summary: AudienceSegmentSummary | None = None


@dataclass
class AudienceSegmentComparison:
    dimension: str
    dimension_label: str
    label: str
    arms: list[SegmentArmSummary]
    diff_summary: str = ""


def detect_themes(text: str) -> list[str]:
    low = text.casefold()
    hits: list[str] = []
    for name, patterns in _THEME_PATTERNS.items():
        if any(re.search(p, low) for p in patterns):
            hits.append(name)
    return hits


def theme_display_label(key: str, *, locale: ReportLocale) -> str:
    labels = _THEME_LABELS_EN if locale == "en" else _THEME_LABELS_SV
    return labels.get(key, key)


def _injection_keywords(bundle: RunBundle) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in bundle.injection_texts or []:
        for kw in _keywords_from_text(str(raw), limit=12):
            if kw not in seen:
                seen.add(kw)
                out.append(kw)
    return out


def interview_relevance(
    snippet: SegmentInterviewSnippet,
    *,
    injection_keywords: list[str],
) -> int:
    """Higher = more useful as a segment quote (themes, injection overlap, substance)."""
    combined = f"{snippet.question} {snippet.answer}".casefold()
    score = 0
    for theme in snippet.themes:
        score += 4
        if theme in _INSIGHT_THEMES:
            score += 3
    for kw in injection_keywords:
        if kw in combined:
            score += 2
    answer_len = len(snippet.answer.strip())
    if answer_len >= 25:
        score += 2
    if answer_len >= 70:
        score += 1
    score += snippet.tick_index
    return score


def rank_interviews_for_display(
    interviews: list[SegmentInterviewSnippet],
    bundle: RunBundle,
    *,
    max_shown: int = MAX_INTERVIEWS_SHOWN,
) -> list[SegmentInterviewSnippet]:
    if not interviews:
        return []
    keywords = _injection_keywords(bundle)
    scored: list[tuple[int, SegmentInterviewSnippet]] = []
    for item in interviews:
        rel = interview_relevance(item, injection_keywords=keywords)
        scored.append(
            (
                rel,
                SegmentInterviewSnippet(
                    agent_name=item.agent_name,
                    question=item.question,
                    answer=item.answer,
                    tick_index=item.tick_index,
                    day=item.day,
                    themes=item.themes,
                    relevance_score=rel,
                    profile_line=item.profile_line,
                ),
            )
        )
    scored.sort(
        key=lambda row: (
            -row[0],
            row[1].tick_index,
            row[1].agent_name.casefold(),
            row[1].question.casefold(),
        )
    )
    return [item for _, item in scored[:max_shown]]


def interview_section_caption(total: int, shown: int, *, locale: ReportLocale) -> str:
    if total <= 0:
        return ""
    if shown >= total:
        if locale == "en":
            return f"Survey Q&A ({total} answers)"
        return f"Enkätfrågor och svar ({total} svar)"
    if locale == "en":
        return f"Survey Q&A (showing {shown} of {total}, ranked by relevance)"
    return f"Enkätfrågor och svar (visar {shown} av {total}, rankade efter relevans)"


def interview_respondent_label(snippet: SegmentInterviewSnippet, *, locale: ReportLocale) -> str:
    if locale == "en":
        day_l = f"Day {snippet.day}"
    else:
        day_l = f"Dag {snippet.day}"
    who = snippet.profile_line or snippet.agent_name
    return f"{day_l} — {who}"


def interview_quote_label(snippet: SegmentInterviewSnippet, *, locale: ReportLocale) -> str:
    return interview_respondent_label(snippet, locale=locale)


def build_segment_narrative(
    seg: AudienceSegmentSummary,
    *,
    locale: ReportLocale,
) -> str:
    tone = seg.tone
    parts: list[str] = []
    if tone and not tone.too_few:
        pos = pct(tone.positive_share)
        crit = pct(tone.critical_share)
        if locale == "en":
            if tone.positive_share >= 0.45:
                parts.append(
                    f"In simulation this group was mostly positive ({pos} positive tone, {crit} critical)."
                )
            elif tone.critical_share >= 0.45:
                parts.append(
                    f"This group was critical ({crit} critical tone, {pos} positive)."
                )
            else:
                parts.append(
                    f"Reception was mixed ({pos} positive, {crit} critical tone in posts and comments)."
                )
            parts.append(
                f"{tone.agent_count} participants wrote {tone.post_count} posts and "
                f"{tone.comment_count} comments ({tone.likes_total} likes, "
                f"{tone.shares_total} shares, engagement score {tone.engagement_score})."
            )
        else:
            if tone.positive_share >= 0.45:
                parts.append(
                    f"I simuleringen var gruppen övervägande positiv "
                    f"({pos} positiv ton, {crit} kritisk)."
                )
            elif tone.critical_share >= 0.45:
                parts.append(
                    f"Gruppen var kritisk ({crit} kritisk ton, {pos} positiv)."
                )
            else:
                parts.append(
                    f"Mottagandet var blandat ({pos} positiv, {crit} kritisk ton "
                    f"i inlägg och kommentarer)."
                )
            parts.append(
                f"{tone.agent_count} deltagare skrev {tone.post_count} inlägg och "
                f"{tone.comment_count} kommentarer ({tone.likes_total} likes, "
                f"{tone.shares_total} delningar, engagemangspoäng {tone.engagement_score})."
            )
    elif tone and tone.too_few:
        if locale == "en":
            parts.append(
                "Too few posts and comments to estimate tone reliably in this segment."
            )
        else:
            parts.append(
                "För få inlägg och kommentarer för att beräkna tonen säkert i segmentet."
            )
        if tone.agent_count:
            if locale == "en":
                parts.append(f"{tone.agent_count} participants matched this segment.")
            else:
                parts.append(f"{tone.agent_count} deltagare matchade segmentet.")
    if seg.themes:
        theme_names = ", ".join(theme_display_label(t, locale=locale) for t in seg.themes)
        if locale == "en":
            parts.append(f"Recurring themes: {theme_names}.")
        else:
            parts.append(f"Återkommande teman: {theme_names}.")
    if seg.interview_total:
        if locale == "en":
            parts.append(
                f"{seg.interview_total} planned survey answers from participants in this group."
            )
        else:
            parts.append(
                f"{seg.interview_total} planerade enkätsvar från deltagare i gruppen."
            )
    if not parts:
        if locale == "en":
            return "No data for this segment in the run."
        return "Ingen data för detta segment i körningen."
    return " ".join(parts)


def _interviews_for_segment(
    bundle: RunBundle,
    *,
    dimension: str,
    value: str,
    locale: ReportLocale = "sv",
) -> list[SegmentInterviewSnippet]:
    agent_bio = build_agent_bio_by_index(bundle)
    out: list[SegmentInterviewSnippet] = []
    for item in extract_interview_qa(bundle):
        bio = agent_bio.get(item.user_id)
        if not bio or segment_value(bio, dimension) != value:
            continue
        combined = f"{item.question} {item.answer}"
        profile = ""
        if bio:
            profile = persona_profile_line(
                bio,
                locale=locale,
                exclude_dimension=dimension,
            )
        out.append(
            SegmentInterviewSnippet(
                agent_name=item.agent_name,
                question=item.question,
                answer=item.answer,
                tick_index=item.tick_index,
                day=item.day,
                themes=detect_themes(combined),
                profile_line=profile,
            )
        )
    return out


def _theme_counts_for_segment(tone: SegmentToneRow | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not tone:
        return counts
    for text in tone.sample_texts:
        for theme in detect_themes(text):
            counts[theme] = counts.get(theme, 0) + 1
    return counts


def _segment_sort_key(dim: str, val: str) -> tuple[int, str, str]:
    order = _DIMENSION_ORDER.index(dim) if dim in _DIMENSION_ORDER else 99
    return (order, dim, val)


def build_audience_summaries(
    bundle: RunBundle,
    classification: BundleClassification,
    *,
    locale: ReportLocale = "sv",
) -> list[AudienceSegmentSummary]:
    tone_rows = build_segment_tone_rows(bundle, classification, locale=locale)
    by_key: dict[tuple[str, str], SegmentToneRow] = {
        (r.dimension, r.label): r for r in tone_rows
    }
    keys = set(by_key)
    for item in extract_interview_qa(bundle):
        bio = build_agent_bio_by_index(bundle).get(item.user_id)
        if not bio:
            continue
        for dim in _DIMENSION_ORDER:
            val = segment_value(bio, dim)
            if val:
                keys.add((dim, val))

    summaries: list[AudienceSegmentSummary] = []
    for dim, val in sorted(keys, key=lambda k: _segment_sort_key(k[0], k[1])):
        tone = by_key.get((dim, val))
        interviews_all = _interviews_for_segment(
            bundle, dimension=dim, value=val, locale=locale
        )
        interviews = rank_interviews_for_display(interviews_all, bundle)
        interview_total = len(interviews_all)
        theme_counts = _theme_counts_for_segment(tone)
        theme_set: set[str] = set(theme_counts)
        for iv in interviews_all:
            theme_set.update(iv.themes)
        if tone and tone.too_few and not interviews_all:
            continue
        summary = AudienceSegmentSummary(
            dimension=dim,
            dimension_label=segment_dimension_label(dim, locale=locale),
            label=val,
            tone=tone,
            interviews=interviews,
            interview_total=interview_total,
            themes=sorted(theme_set),
            theme_counts=theme_counts,
        )
        summary.narrative = build_segment_narrative(summary, locale=locale)
        summaries.append(summary)
    return summaries


def _segment_has_data(summary: AudienceSegmentSummary | None) -> bool:
    if not summary:
        return False
    if summary.interviews or summary.interview_total:
        return True
    tone = summary.tone
    if tone and not tone.too_few:
        return True
    if tone and tone.agent_count:
        return True
    return False


def _positive_tone_for_summary(summary: AudienceSegmentSummary | None) -> float | None:
    if not summary or not summary.tone or summary.tone.too_few:
        return None
    return summary.tone.positive_share


def _critical_tone_for_summary(summary: AudienceSegmentSummary | None) -> float | None:
    if not summary or not summary.tone or summary.tone.too_few:
        return None
    return summary.tone.critical_share


def _engagement_for_summary(summary: AudienceSegmentSummary | None) -> int | None:
    if not summary or not summary.tone:
        return None
    return summary.tone.engagement_score


def _format_arm_diff_line(
    arm_label: str,
    *,
    positive: float | None,
    critical: float | None,
    engagement: int | None,
    locale: ReportLocale,
) -> str:
    bits: list[str] = []
    if positive is not None:
        bits.append(
            f"{pct(positive)} {'positive' if locale == 'en' else 'positiv'}"
        )
    if critical is not None:
        bits.append(
            f"{pct(critical)} {'critical' if locale == 'en' else 'kritisk'}"
        )
    if engagement is not None:
        bits.append(
            f"{'engagement' if locale == 'en' else 'engagemang'} {engagement}"
        )
    if not bits:
        return ""
    return f"{arm_label}: {' · '.join(bits)}"


def build_segment_diff_summary(
    arms: list[SegmentArmSummary],
    *,
    locale: ReportLocale,
) -> str:
    arm_lines: list[str] = []
    positive_scored: list[tuple[str, float]] = []
    critical_scored: list[tuple[str, float]] = []
    engagement_scored: list[tuple[str, int]] = []

    for arm in arms:
        pos = _positive_tone_for_summary(arm.summary)
        crit = _critical_tone_for_summary(arm.summary)
        eng = _engagement_for_summary(arm.summary)
        line = _format_arm_diff_line(
            arm.arm_label,
            positive=pos,
            critical=crit,
            engagement=eng,
            locale=locale,
        )
        if line:
            arm_lines.append(line)
        if pos is not None:
            positive_scored.append((arm.arm_label, pos))
        if crit is not None:
            critical_scored.append((arm.arm_label, crit))
        if eng is not None:
            engagement_scored.append((arm.arm_label, eng))

    if not arm_lines:
        if locale == "en":
            return "Not enough data to compare versions in this segment."
        return "För lite data för att jämföra versionerna i segmentet."

    parts = list(arm_lines)
    if len(arms) >= 2:
        if len(positive_scored) >= 2:
            ordered = sorted(positive_scored, key=lambda row: row[1], reverse=True)
            best_label, best_pos = ordered[0]
            worst_label, worst_pos = ordered[-1]
            gap = best_pos - worst_pos
            if gap >= 0.08:
                if locale == "en":
                    parts.append(f"{best_label} leads on positive tone (+{pct(gap)})")
                else:
                    parts.append(f"{best_label} leder i positiv ton (+{pct(gap)})")
            elif locale == "en":
                parts.append("Versions are close on positive tone")
            else:
                parts.append("Versionerna ligger nära varandra i positiv ton")
        if len(critical_scored) >= 2:
            ordered = sorted(critical_scored, key=lambda row: row[1], reverse=True)
            crit_label, crit_val = ordered[0]
            other_val = ordered[-1][1]
            gap = crit_val - other_val
            if gap >= 0.08:
                if locale == "en":
                    parts.append(f"{crit_label} more critical (+{pct(gap)})")
                else:
                    parts.append(f"{crit_label} mer kritisk (+{pct(gap)})")
        if len(engagement_scored) >= 2:
            ordered = sorted(engagement_scored, key=lambda row: row[1], reverse=True)
            eng_label, eng_val = ordered[0]
            other_eng = ordered[-1][1]
            if eng_val > other_eng:
                if locale == "en":
                    parts.append(
                        f"{eng_label} higher engagement ({eng_val} vs {other_eng})"
                    )
                else:
                    parts.append(
                        f"{eng_label} högre engagemang ({eng_val} vs {other_eng})"
                    )
    return " · ".join(parts)


def build_audience_comparisons(
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale = "sv",
) -> list[AudienceSegmentComparison]:
    per_bundle: list[list[AudienceSegmentSummary]] = [
        build_audience_summaries(bundle, clf, locale=locale)
        for bundle, clf in zip(bundles, classifications, strict=True)
    ]
    by_key: dict[tuple[str, str], dict[str, AudienceSegmentSummary]] = {}
    for bundle, summaries in zip(bundles, per_bundle, strict=True):
        arm = short_bundle_arm_label(bundle)
        for seg in summaries:
            key = (seg.dimension, seg.label)
            by_key.setdefault(key, {})[arm] = seg

    keys = sorted(by_key.keys(), key=lambda k: _segment_sort_key(k[0], k[1]))
    comparisons: list[AudienceSegmentComparison] = []
    arm_order = [short_bundle_arm_label(b) for b in bundles]

    for dim, val in keys:
        seg_map = by_key[(dim, val)]
        arms = [
            SegmentArmSummary(arm_label=arm, summary=seg_map.get(arm))
            for arm in arm_order
        ]
        if not any(_segment_has_data(arm.summary) for arm in arms):
            continue
        dimension_label = segment_dimension_label(dim, locale=locale)
        diff = build_segment_diff_summary(arms, locale=locale)
        comparisons.append(
            AudienceSegmentComparison(
                dimension=dim,
                dimension_label=dimension_label,
                label=val,
                arms=arms,
                diff_summary=diff,
            )
        )
    return comparisons
