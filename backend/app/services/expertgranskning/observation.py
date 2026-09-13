"""Atomic Word-review observations and perspective-safe comment materialization.

Rich expert analysis stays on the observation. The Word margin text is
composed from issue, consequence, and one recommendation. ActorContext is
authoritative for who recommendations address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.expertgranskning.actor_context import ActorContext
from app.services.expertgranskning.schemas import (
    WordExpertComment,
    WordExpertObservation,
)

PERSPECTIVE_USER = "user"
PERSPECTIVE_DOCUMENT_AUTHOR = "document_author"
PERSPECTIVE_COUNTERPART = "counterpart"
PERSPECTIVE_NEUTRAL = "neutral"
PERSPECTIVE_VALUES = frozenset(
    {
        PERSPECTIVE_USER,
        PERSPECTIVE_DOCUMENT_AUTHOR,
        PERSPECTIVE_COUNTERPART,
        PERSPECTIVE_NEUTRAL,
    }
)

WORD_COMMENT_TARGET_MIN_WORDS = 30
WORD_COMMENT_TARGET_MAX_WORDS = 70
WORD_COMMENT_SOFT_CAP_WORDS = 90

_PERSPECTIVE_ALIASES = {
    "user": PERSPECTIVE_USER,
    "reviewer": PERSPECTIVE_USER,
    "the user": PERSPECTIVE_USER,
    "the reviewer": PERSPECTIVE_USER,
    "document_author": PERSPECTIVE_DOCUMENT_AUTHOR,
    "document author": PERSPECTIVE_DOCUMENT_AUTHOR,
    "document authors": PERSPECTIVE_DOCUMENT_AUTHOR,
    "the document author": PERSPECTIVE_DOCUMENT_AUTHOR,
    "the document authors": PERSPECTIVE_DOCUMENT_AUTHOR,
    "author": PERSPECTIVE_DOCUMENT_AUTHOR,
    "authors": PERSPECTIVE_DOCUMENT_AUTHOR,
    "source": PERSPECTIVE_DOCUMENT_AUTHOR,
    "counterpart": PERSPECTIVE_COUNTERPART,
    "audience": PERSPECTIVE_COUNTERPART,
    "the counterpart": PERSPECTIVE_COUNTERPART,
    "the audience": PERSPECTIVE_COUNTERPART,
    "other side": PERSPECTIVE_COUNTERPART,
    "neutral": PERSPECTIVE_NEUTRAL,
    "factual": PERSPECTIVE_NEUTRAL,
    "analytical": PERSPECTIVE_NEUTRAL,
    "": PERSPECTIVE_NEUTRAL,
}

_EN_POSSESSIVES = {
    PERSPECTIVE_USER: "the user's",
    PERSPECTIVE_DOCUMENT_AUTHOR: "the document authors'",
    PERSPECTIVE_COUNTERPART: "the counterpart's",
    PERSPECTIVE_NEUTRAL: "the document authors'",
}
_SV_POSSESSIVES = {
    PERSPECTIVE_USER: "användarens",
    PERSPECTIVE_DOCUMENT_AUTHOR: "dokumentförfattarnas",
    PERSPECTIVE_COUNTERPART: "motpartens",
    PERSPECTIVE_NEUTRAL: "dokumentförfattarnas",
}
_SWEDISH_DETERMINERS = frozenset({"ditt", "din", "ert", "er"})

_POSSESSIVE_CLAIM_RE = re.compile(
    r"\b(?P<det>your|ditt|din|ert|er)\s+"
    r"(?P<noun>strongest argument|claim|request|argument|yrkande|"
    r"begäran|påstående)\b",
    re.IGNORECASE,
)

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class WordExpertCommentDraft:
    """Materialized short comment plus the internal observation fields."""

    kommentar: str
    issue: str = ""
    analysis: str = ""
    source_perspective: str = ""
    target_perspective: str = ""
    statement_owner: str = ""
    recommendation_recipient: str = ""
    consequence: str = ""
    recommended_action: str = ""

    def has_visible_comment(self) -> bool:
        return bool(self.kommentar.strip())


def normalize_perspective(value: str) -> str:
    folded = (value or "").strip().casefold()
    if folded in _PERSPECTIVE_ALIASES:
        return _PERSPECTIVE_ALIASES[folded]
    if folded in PERSPECTIVE_VALUES:
        return folded
    return folded


def statement_owner_kind(value: str) -> str:
    kind = normalize_perspective(value)
    if kind in PERSPECTIVE_VALUES:
        return kind
    return PERSPECTIVE_NEUTRAL if not kind else PERSPECTIVE_DOCUMENT_AUTHOR


def possessive_owner_phrase(value: str, *, swedish: bool) -> str:
    kind = statement_owner_kind(value)
    table = _SV_POSSESSIVES if swedish else _EN_POSSESSIVES
    if normalize_perspective(value) in PERSPECTIVE_VALUES or not (value or "").strip():
        return table[kind]
    label = value.strip()
    if swedish:
        return label
    if label.endswith("s"):
        return f"{label}'"
    return f"{label}'s"


def comment_word_count(text: str) -> int:
    return len((text or "").split())


def comment_exceeds_soft_cap(text: str) -> bool:
    return comment_word_count(text) > WORD_COMMENT_SOFT_CAP_WORDS


def observation_has_content(item: WordExpertObservation) -> bool:
    return bool(
        item.issue
        or item.kommentar
        or item.analysis
        or item.consequence
        or item.recommended_action
    )


def comment_misattributes_user_claim(
    text: str,
    statement_owner: str,
) -> bool:
    owner = statement_owner_kind(statement_owner)
    if owner == PERSPECTIVE_USER:
        return False
    return bool(_POSSESSIVE_CLAIM_RE.search(text or ""))


def rewrite_non_user_possessives(text: str, statement_owner: str) -> str:
    if not comment_misattributes_user_claim(text, statement_owner):
        return text

    def replace(match: re.Match[str]) -> str:
        swedish = match.group("det").casefold() in _SWEDISH_DETERMINERS
        phrase = possessive_owner_phrase(statement_owner, swedish=swedish)
        return f"{phrase} {match.group('noun')}"

    return _POSSESSIVE_CLAIM_RE.sub(replace, text)


def _squash_spaces(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def materialize_word_comment(
    *,
    issue: str = "",
    consequence: str = "",
    recommended_action: str = "",
    kommentar: str = "",
    statement_owner: str = "",
) -> str:
    """Compose the Word margin text. Do not truncate a long analysis."""
    parts = [
        part
        for part in (issue.strip(), consequence.strip(), recommended_action.strip())
        if part
    ]
    text = " ".join(parts) if parts else kommentar.strip()
    text = rewrite_non_user_possessives(text, statement_owner)
    return _squash_spaces(text)


def materialize_observation_comment(
    item: WordExpertObservation | WordExpertCommentDraft,
) -> str:
    return materialize_word_comment(
        issue=item.issue,
        consequence=item.consequence,
        recommended_action=item.recommended_action,
        kommentar=item.kommentar,
        statement_owner=item.statement_owner,
    )


def bind_actor_attribution(
    item: WordExpertObservation,
    actor: ActorContext | None,
) -> WordExpertObservation:
    """ActorContext decides the recommendation recipient when perspective is known."""
    if actor is None or not actor.perspective_known:
        return item
    return item.model_copy(update={"recommendation_recipient": PERSPECTIVE_USER})


def expand_expert_comment(parsed: WordExpertComment) -> list[WordExpertObservation]:
    """One expert call may emit several atomic observations."""
    atoms = [item for item in parsed.observations if observation_has_content(item)]
    if atoms:
        return atoms
    if observation_has_content(parsed):
        return [
            WordExpertObservation(
                issue=parsed.issue,
                analysis=parsed.analysis,
                source_perspective=parsed.source_perspective,
                target_perspective=parsed.target_perspective,
                statement_owner=parsed.statement_owner,
                recommendation_recipient=parsed.recommendation_recipient,
                consequence=parsed.consequence,
                recommended_action=parsed.recommended_action,
                kommentar=parsed.kommentar,
                anchor_paragraph_index=parsed.anchor_paragraph_index,
            )
        ]
    return []


def draft_from_observation(
    item: WordExpertObservation,
    actor: ActorContext | None = None,
) -> WordExpertCommentDraft:
    bound = bind_actor_attribution(item, actor)
    return WordExpertCommentDraft(
        kommentar=materialize_observation_comment(bound),
        issue=bound.issue,
        analysis=bound.analysis,
        source_perspective=bound.source_perspective,
        target_perspective=bound.target_perspective,
        statement_owner=bound.statement_owner,
        recommendation_recipient=bound.recommendation_recipient,
        consequence=bound.consequence,
        recommended_action=bound.recommended_action,
    )


def issue_text_for_match(*, issue: str, kommentar: str) -> str:
    return (issue or "").strip() or (kommentar or "").strip()
