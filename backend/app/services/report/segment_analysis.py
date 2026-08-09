"""Målgruppsanalys: bio segments × SSR + interview themes (rule-based, no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, _keywords_from_text
from app.services.report.locale import ReportLocale
from app.services.report.persona_bio import build_agent_bio_by_index, segment_value
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

MAX_INTERVIEWS_SHOWN = 3
_INSIGHT_THEMES = frozenset({"finansiering", "vaghet", "konkret"})
# Interview quotes render under this dimension only — avoids duplicate quotes on ort/lutning rows.
INTERVIEW_QUOTE_DIMENSION = "livssituation"


@dataclass
class SegmentInterviewSnippet:
    agent_name: str
    question: str
    answer: str
    tick_index: int = 0
    day: int = 1
    themes: list[str] = field(default_factory=list)
    relevance_score: int = 0


@dataclass
class AudienceSegmentSummary:
    dimension: str
    dimension_label: str
    label: str
    tone: SegmentToneRow | None
    interviews: list[SegmentInterviewSnippet] = field(default_factory=list)
    interview_total: int = 0
    themes: list[str] = field(default_factory=list)


def detect_themes(text: str) -> list[str]:
    low = text.casefold()
    hits: list[str] = []
    for name, patterns in _THEME_PATTERNS.items():
        if any(re.search(p, low) for p in patterns):
            hits.append(name)
    return hits


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
            return f"Survey answers (all {total})"
        return f"Enkätsvar (alla {total})"
    if locale == "en":
        return f"Survey answers (showing {shown} most relevant of {total})"
    return f"Enkätsvar (visar {shown} mest relevanta av {total})"


def interview_quote_label(snippet: SegmentInterviewSnippet, *, locale: ReportLocale) -> str:
    if locale == "en":
        return (
            f"After day {snippet.day} — "
            f"{snippet.agent_name} (survey)"
        )
    return (
        f"Efter dag {snippet.day} — "
        f"{snippet.agent_name} (enkät)"
    )


def _interviews_for_segment(
    bundle: RunBundle,
    *,
    dimension: str,
    value: str,
) -> list[SegmentInterviewSnippet]:
    agent_bio = build_agent_bio_by_index(bundle)
    out: list[SegmentInterviewSnippet] = []
    for item in extract_interview_qa(bundle):
        bio = agent_bio.get(item.user_id)
        if not bio or segment_value(bio, dimension) != value:
            continue
        combined = f"{item.question} {item.answer}"
        out.append(
            SegmentInterviewSnippet(
                agent_name=item.agent_name,
                question=item.question,
                answer=item.answer,
                tick_index=item.tick_index,
                day=item.day,
                themes=detect_themes(combined),
            )
        )
    return out


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
        for dim in ("livssituation", "ort", "lutning"):
            val = segment_value(bio, dim)
            if val:
                keys.add((dim, val))

    summaries: list[AudienceSegmentSummary] = []
    for dim, val in sorted(keys):
        tone = by_key.get((dim, val))
        interviews_all = _interviews_for_segment(bundle, dimension=dim, value=val)
        if dim == INTERVIEW_QUOTE_DIMENSION:
            interviews = rank_interviews_for_display(interviews_all, bundle)
            interview_total = len(interviews_all)
        else:
            interviews = []
            interview_total = 0
        theme_set: set[str] = set()
        for iv in interviews_all:
            theme_set.update(iv.themes)
        if tone and tone.too_few and not interviews_all:
            continue
        if (
            dim != INTERVIEW_QUOTE_DIMENSION
            and interviews_all
            and (tone is None or tone.too_few)
        ):
            continue
        summaries.append(
            AudienceSegmentSummary(
                dimension=dim,
                dimension_label=segment_dimension_label(dim, locale=locale),
                label=val,
                tone=tone,
                interviews=interviews,
                interview_total=interview_total,
                themes=sorted(theme_set),
            )
        )
    return summaries
