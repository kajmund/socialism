"""Shared Word-review test builders."""

from __future__ import annotations

from app.services.expertgranskning.observation import (
    PERSPECTIVE_DOCUMENT_AUTHOR,
    PERSPECTIVE_USER,
)
from app.services.expertgranskning.schemas import WordExpertComment, WordExpertObservation

DEFAULT_WORD_ATTRIBUTION = {
    "source_perspective": PERSPECTIVE_DOCUMENT_AUTHOR,
    "target_perspective": PERSPECTIVE_USER,
    "statement_owner": PERSPECTIVE_DOCUMENT_AUTHOR,
    "recommendation_recipient": PERSPECTIVE_USER,
}


def word_expert_observation(**overrides) -> WordExpertObservation:
    payload = {**DEFAULT_WORD_ATTRIBUTION, **overrides}
    return WordExpertObservation(**payload)


def word_expert_comment(**overrides) -> WordExpertComment:
    payload = {**DEFAULT_WORD_ATTRIBUTION, **overrides}
    return WordExpertComment(**payload)
