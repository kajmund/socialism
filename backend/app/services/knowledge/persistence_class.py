"""Domain-free persistence classes for extracted knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.knowledge.identity import normalize_assertion_text

DOMAIN_KNOWLEDGE = "domain_knowledge"
SOURCE_QUALITY = "source_quality"
RESEARCH_OBSERVATION = "research_observation"

PersistenceClass = Literal[
    "domain_knowledge",
    "source_quality",
    "research_observation",
]
PERSISTENCE_CLASSES = frozenset(
    {DOMAIN_KNOWLEDGE, SOURCE_QUALITY, RESEARCH_OBSERVATION}
)

SOURCE_QUALITY_KINDS = frozenset(
    {
        "corrupted",
        "incomplete_source",
        "incorrect_source",
        "ocr",
        "partial_source",
        "retrieval_limit",
        "source_gap",
        "truncation",
    }
)
RESEARCH_OBS_KINDS = frozenset(
    {
        "does_not_answer",
        "gap",
        "insufficiency",
        "question_relative_gap",
        "unanswered",
    }
)

_SOURCE_QUALITY_PHRASES = (
    "corrupt",
    "corrupted",
    "fel källa",
    "felaktig källa",
    "fullständiga domskäl saknas",
    "fullständiga skäl saknas",
    "incomplete source",
    "incorrect source",
    "korrupt",
    "ocr",
    "ofullständig källa",
    "partial source",
    "referatet är trunkerat",
    "retrieval limit",
    "retrieval limitation",
    "source is incomplete",
    "source is truncated",
    "truncated",
    "truncation",
    "trunkerad",
    "trunkerat",
    "trunkering",
    "wrong source",
)
_RESEARCH_OBS_PHRASES = (
    "besvarar inte",
    "cannot answer",
    "does not address",
    "does not answer",
    "insufficient to answer",
    "källan besvarar inte",
    "no answer in",
    "source does not answer",
    "source does not contain an answer",
    "unanswered by this source",
)


@dataclass(frozen=True)
class PersistenceDecision:
    persistence_class: PersistenceClass
    kind: str
    reason: str
    statement_normalized: str


class PersistenceClassError(ValueError):
    """A persistence class or kind is invalid."""


def require_persistence_class(value: str) -> PersistenceClass:
    text = value.strip()
    if text not in PERSISTENCE_CLASSES:
        raise PersistenceClassError(f"unknown persistence class: {value!r}")
    return text  # type: ignore[return-value]


def classify_persistence(
    *,
    value: dict[str, object],
    declared_class: str | None = None,
    declared_kind: str | None = None,
) -> PersistenceDecision:
    """Classify an extracted assertion. Domain-free; producers may declare class."""
    statement = _statement_text(value)
    normalized = normalize_assertion_text(statement) if statement else ""
    if declared_class:
        persistence_class = require_persistence_class(declared_class)
        kind = _declared_kind(persistence_class, declared_kind, value)
        return PersistenceDecision(
            persistence_class=persistence_class,
            kind=kind,
            reason="declared",
            statement_normalized=normalized,
        )
    kind_hint = _kind_hint(declared_kind, value)
    if kind_hint in SOURCE_QUALITY_KINDS:
        return PersistenceDecision(
            persistence_class=SOURCE_QUALITY,
            kind=kind_hint,
            reason="structured_kind",
            statement_normalized=normalized,
        )
    if kind_hint in RESEARCH_OBS_KINDS:
        return PersistenceDecision(
            persistence_class=RESEARCH_OBSERVATION,
            kind=kind_hint,
            reason="structured_kind",
            statement_normalized=normalized,
        )
    if normalized and _contains_phrase(normalized, _SOURCE_QUALITY_PHRASES):
        return PersistenceDecision(
            persistence_class=SOURCE_QUALITY,
            kind=_source_quality_kind(normalized),
            reason="source_quality_marker",
            statement_normalized=normalized,
        )
    if normalized and _contains_phrase(normalized, _RESEARCH_OBS_PHRASES):
        return PersistenceDecision(
            persistence_class=RESEARCH_OBSERVATION,
            kind="does_not_answer",
            reason="research_observation_marker",
            statement_normalized=normalized,
        )
    return PersistenceDecision(
        persistence_class=DOMAIN_KNOWLEDGE,
        kind="assertion",
        reason="domain_default",
        statement_normalized=normalized,
    )


def _declared_kind(
    persistence_class: PersistenceClass,
    declared_kind: str | None,
    value: dict[str, object],
) -> str:
    kind = _kind_hint(declared_kind, value)
    if persistence_class == SOURCE_QUALITY:
        return kind if kind in SOURCE_QUALITY_KINDS else "source_gap"
    if persistence_class == RESEARCH_OBSERVATION:
        return kind if kind in RESEARCH_OBS_KINDS else "does_not_answer"
    return kind or "assertion"


def _kind_hint(declared_kind: str | None, value: dict[str, object]) -> str:
    if declared_kind and declared_kind.strip():
        return declared_kind.strip()
    raw = value.get("kind")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ""


def _statement_text(value: dict[str, object]) -> str:
    for key in ("statement", "value", "text"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw
    return ""


def _contains_phrase(normalized: str, phrases: tuple[str, ...]) -> bool:
    return any(normalize_assertion_text(phrase) in normalized for phrase in phrases)


def _source_quality_kind(normalized: str) -> str:
    if _contains_phrase(normalized, ("ocr",)):
        return "ocr"
    if _contains_phrase(normalized, ("corrupt", "corrupted", "korrupt")):
        return "corrupted"
    if _contains_phrase(
        normalized,
        ("incorrect source", "wrong source", "fel källa", "felaktig källa"),
    ):
        return "incorrect_source"
    if _contains_phrase(normalized, ("retrieval limit", "retrieval limitation")):
        return "retrieval_limit"
    if _contains_phrase(
        normalized,
        (
            "truncated",
            "truncation",
            "trunkerat",
            "trunkerad",
            "trunkering",
            "referatet är trunkerat",
        ),
    ):
        return "truncation"
    if _contains_phrase(normalized, ("partial source",)):
        return "partial_source"
    return "incomplete_source"
