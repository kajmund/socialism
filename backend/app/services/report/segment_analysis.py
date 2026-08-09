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
    if snippet.profile_line:
        return f"{day_l} — {snippet.agent_name} ({snippet.profile_line})"
    return f"{day_l} — {snippet.agent_name}"


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
