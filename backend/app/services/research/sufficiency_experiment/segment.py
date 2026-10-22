"""Semantic passage segmentation with full character coverage."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from app.services.research.assessment import AssessableEvidence
from app.services.research.sufficiency_experiment.types import (
    EvidencePassage,
    evidence_need_ids,
)

_PARAGRAPH = re.compile(r"\n[ \t\r]*\n+")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_SPACE = re.compile(r"\s+")


class CoverageError(ValueError):
    """A source character was not assigned to any passage."""


def segment_text(text: str, *, max_chars: int) -> list[tuple[int, int, str]]:
    if max_chars < 1:
        raise CoverageError("max_chars must be positive")
    if text == "":
        return [(0, 0, "")]
    spans: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            end = start + _semantic_cut(text[start:end])
        if end <= start:
            end = min(start + max_chars, len(text))
        spans.append((start, end, text[start:end]))
        start = end
    _assert_full_cover(text, spans)
    return spans


def segment_evidence(
    evidence: Sequence[AssessableEvidence],
    *,
    max_chars: int,
) -> list[EvidencePassage]:
    passages: list[EvidencePassage] = []
    for item in evidence:
        text = item.excerpt or ""
        spans = segment_text(text, max_chars=max_chars)
        need_ids = evidence_need_ids(item)
        for ordinal, (start, end, part) in enumerate(spans):
            passages.append(
                EvidencePassage(
                    passage_id=f"{item.evidence_id}:p{ordinal}",
                    evidence_id=item.evidence_id,
                    research_need_ids=need_ids,
                    start=start,
                    end=end,
                    text=part,
                    content_hash=_hash_text(part),
                    source_chars=len(text),
                )
            )
    return passages


def _semantic_cut(window: str) -> int:
    for pattern in (_PARAGRAPH, _SENTENCE, _SPACE):
        matches = list(pattern.finditer(window))
        if not matches:
            continue
        cut = matches[-1].end()
        if cut > len(window) // 4:
            return cut
    return len(window)


def _assert_full_cover(text: str, spans: Sequence[tuple[int, int, str]]) -> None:
    covered = 0
    expected = 0
    for start, end, part in spans:
        if start != expected or part != text[start:end]:
            raise CoverageError("passages are not a contiguous cover of the source")
        covered += end - start
        expected = end
    if covered != len(text) or expected != len(text):
        raise CoverageError("passages do not cover every source character")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
