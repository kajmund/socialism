"""Deterministic citation parsing and legal-need anchoring.

Planner output is model-generated: it can switch language and drop the
objective's law citation. The live diagnostic showed English needs with
``§ 36``/NBSP reaching retrieval, where resolve/search then fail. These helpers
are deterministic guards, not prompt changes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from app.services.research.followup import FollowUpNeedDraft
from app.services.research.models import ResearchNeed, ResearchSourceType
from app.services.research.planner import ResearchNeedDraft

_LEGAL_RESEARCH_SOURCE_TYPES = frozenset(
    {"swedish_law", "swedish_case_law", "swedish_preparatory_works"}
)

_CITATION_HINT = re.compile(
    r"("
    r"§|"
    r"\bkap\.|"
    r"\bSFS\b|"
    r"\b\d{4}:\d+\b|"
    r"\bprop\.\s*\d{4}/\d{2}:\d+|"
    r"\bSOU\s+\d{4}:\d+|"
    r"\bNJA\s+\d{4}|"
    r"\bart(?:ikel|\.)?\s*\d+"
    r")",
    re.IGNORECASE,
)
_CASE_CITATION = re.compile(
    r"\b(?:NJA|AD|MÖD|HFD|RÅ)\s+\d{4}(?:\s+(?:s\.\s*\d+|nr\s+\d+))?",
    re.IGNORECASE,
)
_PREPARATORY_CITATION = re.compile(
    r"\b(?:prop(?:osition)?\.?\s*\d{4}(?:/\d{2})?:\d+|SOU\s+\d{4}:\d+|"
    r"bet(?:änkande)?\.?\s*\d{4}/\d{2}:[A-Za-z]+\d+)",
    re.IGNORECASE,
)
_PROVISION_CITATION = re.compile(r"(?:§\s*\d+|\b\d+\s*§)")

_SECTION_REFERENCE = re.compile(r"(?:\b(\d+)\s*§|§\s*(\d+))")
_LAW_REFERENCE = re.compile(r"\b([A-Za-zÅÄÖåäö][A-Za-zÅÄÖåäö]*lagen)\b", re.IGNORECASE)
_CASE_REFERENCE = re.compile(
    r"\b(?:NJA|AD|MÖD|HFD|RÅ)\s+\d{4}(?:\s+(?:s\.\s*\d+|nr\s+\d+))?",
    re.IGNORECASE,
)
_PREPARATORY_REFERENCE = re.compile(r"\b(?:prop\.?|SOU|bet\.?)\s*\d{4}", re.IGNORECASE)
_SFS_REFERENCE = re.compile(r"\b\d{4}:\d+\b")
_ARTICLE_CITATION = re.compile(r"\bart(?:ikel|\.)?\s*\d+", re.IGNORECASE)

_SWEDISH_QUESTION_WORDS = frozenset(
    {
        "att", "av", "avgöranden", "behöver", "citaten", "den", "det", "domstol",
        "domstolar", "eller", "enligt", "exempel", "faktiskt", "finns", "frågan",
        "för", "har", "hur", "här", "i", "inte", "jämkats", "jämkning", "lagen",
        "med", "men", "och", "om", "på", "som", "samt", "skulle", "svenska",
        "till", "tillämpat", "under", "vad", "var", "vilka", "vilken", "vilket",
        "är",
    }
)
_ENGLISH_QUESTION_WORDS = frozenset(
    {
        "a", "an", "and", "applied", "are", "as", "at", "be", "by", "case",
        "cases", "contract", "contracts", "court", "courts", "decisions", "do",
        "does", "exact", "for", "from", "has", "have", "how", "in", "is", "it",
        "of", "on", "or", "that", "the", "their", "this", "to", "was", "were",
        "what", "when", "which", "who", "with", "wording",
    }
)


def normalise_citation_text(value: str) -> str:
    """Make NBSP and non-breaking hyphen variants visible to the citation regexes."""
    return (
        value.replace("\u202f", " ")
        .replace("\u00a0", " ")
        .replace("\u2007", " ")
        .replace("\u2009", " ")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
    )


def looks_like_citation(question: str) -> bool:
    return _CITATION_HINT.search(normalise_citation_text(question)) is not None


def looks_like_case_citation(question: str) -> bool:
    return _CASE_CITATION.search(normalise_citation_text(question)) is not None


def _citation_from_text(value: str) -> str | None:
    text = normalise_citation_text(value)
    section = _SECTION_REFERENCE.search(text)
    law = _LAW_REFERENCE.search(text)
    if section is None or law is None:
        return None
    number = section.group(1) or section.group(2)
    return f"{number} § {law.group(1)}"


def _has_citation(value: str) -> bool:
    if _citation_from_text(value) is not None:
        return True
    text = normalise_citation_text(value)
    return bool(
        _CASE_REFERENCE.search(text)
        or _PREPARATORY_REFERENCE.search(text)
        or _SFS_REFERENCE.search(text)
    )


def _is_swedish_question(value: str) -> bool:
    words = re.findall(r"[a-zåäö]+", normalise_citation_text(value).casefold())
    if not words:
        return True
    swedish = sum(1 for word in words if word in _SWEDISH_QUESTION_WORDS)
    english = sum(1 for word in words if word in _ENGLISH_QUESTION_WORDS)
    return english <= swedish


def _anchored_question(source_types: Sequence[str], citation: str) -> str:
    source_type = next(
        (item for item in source_types if item in _LEGAL_RESEARCH_SOURCE_TYPES),
        "swedish_case_law",
    )
    if source_type == "swedish_case_law":
        return f"Vilka avgöranden har tillämpat {citation}?"
    if source_type == "swedish_preparatory_works":
        return f"Vad säger förarbetena till {citation}?"
    return f"Vad säger {citation}?"


def plan_objective(plan: object) -> str:
    needs = getattr(plan, "needs", ())
    for need in needs:
        if getattr(need, "id", "") == "research-main":
            return str(getattr(need, "question", ""))
    return str(getattr(needs[0], "question", "")) if needs else ""


def _is_legal(source_types: Sequence[str]) -> bool:
    return any(item in _LEGAL_RESEARCH_SOURCE_TYPES for item in source_types)


def anchor_research_drafts(
    drafts: Sequence[ResearchNeedDraft], *, objective: str
) -> list[ResearchNeedDraft]:
    citation = _citation_from_text(objective)
    if citation is None:
        return list(drafts)
    anchored: list[ResearchNeedDraft] = []
    for draft in drafts:
        if not _is_legal(draft.source_types):
            anchored.append(draft)
            continue
        if _is_swedish_question(draft.question) and _has_citation(draft.question):
            anchored.append(draft)
            continue
        anchored.append(
            replace(
                draft,
                question=_anchored_question(draft.source_types, citation),
                original_question=draft.original_question or draft.question,
                normalization_reason="objective_citation_anchor",
                already_normalized=True,
            )
        )
    return anchored


def anchor_follow_up_drafts(
    drafts: Sequence[FollowUpNeedDraft], *, objective: str
) -> list[FollowUpNeedDraft]:
    citation = _citation_from_text(objective)
    if citation is None:
        return list(drafts)
    anchored: list[FollowUpNeedDraft] = []
    for draft in drafts:
        if not _is_legal(draft.source_types):
            anchored.append(draft)
            continue
        if _is_swedish_question(draft.question) and _has_citation(draft.question):
            anchored.append(draft)
            continue
        anchored.append(
            replace(
                draft,
                question=_anchored_question(draft.source_types, citation),
                original_question=draft.original_question or draft.question,
                normalization_reason="objective_citation_anchor",
                already_normalized=True,
            )
        )
    return anchored


def resolution_query(need: ResearchNeed, source_type: ResearchSourceType) -> str | None:
    question = normalise_citation_text(need.question)
    if source_type == "swedish_preparatory_works":
        match = _PREPARATORY_CITATION.search(question)
        if match is not None:
            return match.group(0)
    if source_type == "swedish_case_law":
        match = _CASE_CITATION.search(question)
        if match is not None:
            return match.group(0)
    if source_type == "swedish_law":
        for pattern in (_SFS_REFERENCE, _ARTICLE_CITATION):
            match = pattern.search(question)
            if match is not None:
                return match.group(0)
    return provision_resolution_query(question)


def provision_resolution_query(question: str) -> str | None:
    text = normalise_citation_text(question)
    provision = _PROVISION_CITATION.search(text)
    if provision is None:
        return None
    law = re.search(r"\b[A-Za-zÅÄÖåäö]+lagen\b", text, re.IGNORECASE)
    if law is None:
        return None
    return f"{provision.group(0)} {law.group(0)}"


def select_lagen_nu_flow(need: ResearchNeed) -> str:
    caps = {item.strip().lower() for item in need.capabilities if item.strip()}
    if "resolve_citation" in caps or "resolve" in caps:
        return "resolve"
    if "search" in caps:
        return "search"
    source_type = need.source_types[0] if need.source_types else "swedish_law"
    return "resolve" if resolution_query(need, source_type) is not None else "search"
