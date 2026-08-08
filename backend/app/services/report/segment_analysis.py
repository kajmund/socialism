"""Målgruppsanalys: bio segments × SSR + interview themes (rule-based, no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification
from app.services.report.locale import ReportLocale
from app.services.report.persona_bio import build_agent_bio_by_index, segment_value
from app.services.report.segment_ssr import (
    SegmentToneRow,
    build_segment_tone_rows,
    segment_dimension_label,
)
from app.services.report.tick_report import InterviewQA, extract_interview_qa

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


@dataclass
class SegmentInterviewSnippet:
    agent_name: str
    question: str
    answer: str
    themes: list[str] = field(default_factory=list)


@dataclass
class AudienceSegmentSummary:
    dimension: str
    dimension_label: str
    label: str
    tone: SegmentToneRow | None
    interviews: list[SegmentInterviewSnippet] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)


def detect_themes(text: str) -> list[str]:
    low = text.casefold()
    hits: list[str] = []
    for name, patterns in _THEME_PATTERNS.items():
        if any(re.search(p, low) for p in patterns):
            hits.append(name)
    return hits


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
        interviews = _interviews_for_segment(bundle, dimension=dim, value=val)
        theme_set: set[str] = set()
        for iv in interviews:
            theme_set.update(iv.themes)
        if tone and tone.too_few and not interviews:
            continue
        summaries.append(
            AudienceSegmentSummary(
                dimension=dim,
                dimension_label=segment_dimension_label(dim, locale=locale),
                label=val,
                tone=tone,
                interviews=interviews,
                themes=sorted(theme_set),
            )
        )
    return summaries
