"""Complete EvidenceSet segmentation never drops source characters."""

from __future__ import annotations

import pytest

from app.services.research.sufficiency_experiment.golden import (
    CONTRADICTION_SIGNAL,
    large_567k,
    tail_counterevidence,
)
from app.services.research.sufficiency_experiment.segment import (
    CoverageError,
    _assert_full_cover,
    segment_evidence,
    segment_text,
)
from app.services.research.sufficiency_experiment.types import MAX_PASSAGE_CHARS


def test_segment_text_covers_every_character() -> None:
    text = "A" * 80 + "\n\n" + "B" * 80 + " " + CONTRADICTION_SIGNAL
    spans = segment_text(text, max_chars=64)
    assert "".join(part for _, _, part in spans) == text
    assert CONTRADICTION_SIGNAL in "".join(part for _, _, part in spans)


def test_tail_counterevidence_keeps_the_contradiction() -> None:
    case = tail_counterevidence()
    passages = segment_evidence(case.evidence, max_chars=MAX_PASSAGE_CHARS)
    joined = "".join(item.text for item in passages if item.evidence_id == "evidence-0")
    assert joined == case.evidence[0].excerpt
    assert any(CONTRADICTION_SIGNAL in item.text for item in passages)


def test_large_case_covers_every_excerpt() -> None:
    case = large_567k()
    passages = segment_evidence(case.evidence, max_chars=MAX_PASSAGE_CHARS)
    for item in case.evidence:
        owned = [row for row in passages if row.evidence_id == item.evidence_id]
        assert "".join(row.text for row in owned) == (item.excerpt or "")


def test_lost_span_fails_loudly() -> None:
    with pytest.raises(CoverageError):
        _assert_full_cover("abcdef", [(0, 3, "abc")])
