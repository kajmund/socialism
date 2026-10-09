"""Local classification of user speech while the assistant is talking."""

from __future__ import annotations

import re
from typing import Literal

from app.config import settings

BackchannelKind = Literal["backchannel", "interruption", "new_question", "uncertain"]

_PUNCT = re.compile(r"[^\w\s?åäöÅÄÖ-]+", re.UNICODE)
_SPACES = re.compile(r"\s+")
URGENT = frozenset({"stopp", "nej", "vänta", "stop", "wait", "no"})
BACKCHANNELS = frozenset(
    {
        "mm",
        "mhm",
        "mm hm",
        "mmhm",
        "just det",
        "jajust",
        "ja precis",
        "okej",
        "ok",
        "ja",
        "jaha",
        "aha",
        "hm",
        "hmm",
    }
)
_QUESTION_STARTS = ("vad", "hur", "varför", "varfor", "vilken", "vilket", "kan du", "skulle")
_INTERRUPT_STARTS = ("ja men", "ja men ", "nej men", "okej men", "ok men")


def normalize_utterance(text: str) -> str:
    folded = _PUNCT.sub(" ", text.casefold())
    return _SPACES.sub(" ", folded).strip()


def classify_utterance(
    text: str,
    *,
    duration_ms: float | None = None,
    echoed: str | None = None,
) -> BackchannelKind:
    normalized = normalize_utterance(text)
    if not normalized:
        kind: BackchannelKind = "uncertain"
    elif echoed and normalize_utterance(echoed) == normalized:
        kind = "backchannel"
    elif _urgent(normalized) or _interrupts(normalized):
        kind = "interruption"
    elif "?" in text or normalized.startswith(_QUESTION_STARTS):
        kind = "new_question"
    elif _backchannel_only(normalized) and (
        duration_ms is None or duration_ms <= settings.live_speech_backchannel_max_ms
    ):
        kind = "backchannel"
    else:
        kind = "uncertain"
    return kind


def _interrupts(normalized: str) -> bool:
    return any(normalized.startswith(prefix) for prefix in _INTERRUPT_STARTS) or (
        " men " in f" {normalized} " and not _backchannel_only(normalized)
    )


def _urgent(normalized: str) -> bool:
    tokens = set(normalized.split())
    return bool(tokens & URGENT) or normalized in URGENT


def _backchannel_only(normalized: str) -> bool:
    if normalized in BACKCHANNELS:
        return True
    tokens = normalized.split()
    return bool(tokens) and all(token in BACKCHANNELS or token in {"mm", "okej", "ok"} for token in tokens)
