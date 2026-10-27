"""PR #420 budgeted Cerebras baseline view. Does not call a live model."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.research.assessment_input import (
    ASSESSMENT_MAX_INPUT_CHARS,
    encode_assessment_input,
)

TRUNCATION_MARK = "…[trunkerad]"
PR420_INPUT_CHARS_BEFORE = 567_673
PR420_INPUT_CHARS_AFTER = 56_443
PR420_MODEL = "cerebras gpt-oss-120b"
PR420_OUTPUT_CAP_TOKENS = 8_192


@dataclass(frozen=True)
class BaselineView:
    payload: dict[str, object]
    encoded_chars: int
    source_chars: int
    omitted_evidence_ids: tuple[str, ...]
    truncated: bool
    visible_text: str

    @property
    def coverage(self) -> float:
        if self.source_chars <= 0:
            return 1.0
        visible = self.encoded_chars
        return min(1.0, visible / self.source_chars)

    def contains(self, signal: str) -> bool:
        return signal in self.visible_text


def baseline_rows(evidence: Sequence[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in evidence:
        rows.append(
            {
                "evidence_id": item.evidence_id,
                "research_need_id": item.research_need_id,
                "research_need_ids": list(getattr(item, "research_need_ids", ()) or ()),
                "duplicate_evidence_ids": [],
                "status": item.status,
                "title": item.title,
                "excerpt": item.excerpt,
                "source_id": item.source_id,
                "source_url": item.source_url,
                "provenance": dict(item.provenance),
                "legal_result": None,
                "claims": [],
            }
        )
    return rows


def baseline_view(
    evidence: Sequence[object],
    *,
    max_chars: int = ASSESSMENT_MAX_INPUT_CHARS,
) -> BaselineView:
    rows = baseline_rows(evidence)
    encoded = encode_assessment_input(rows, max_chars=max_chars)
    raw = json.dumps(encoded.payload, ensure_ascii=False, separators=(",", ":"))
    source = sum(len(getattr(item, "excerpt", None) or "") for item in evidence)
    omitted = tuple(item for item in encoded.omitted_evidence_ids if item)
    return BaselineView(
        payload=encoded.payload,
        encoded_chars=len(raw),
        source_chars=source,
        omitted_evidence_ids=omitted,
        truncated=TRUNCATION_MARK in raw or bool(omitted),
        visible_text=raw,
    )


def baseline_verdict(view: BaselineView, *, expected: str, signal: str) -> str:
    """Judge from the budgeted window only. Missing signal cannot be seen."""
    if expected == "insufficient" and signal and not view.contains(signal):
        return "sufficient"
    if expected == "sufficient" and signal and not view.contains(signal):
        return "insufficient"
    return expected
