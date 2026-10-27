"""SSR-only Tabular Review value types. No Jev, no value extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CellStatus = Literal["hit", "no_hit", "unknown", "negative_hit"]
CellPolarity = Literal["positive", "negative"]
ReviewState = Literal["pending", "approved", "rejected"]
LabelVerdict = Literal["match", "not_match"]

NO_HIT = "no_hit"
HIT = "hit"
UNKNOWN = "unknown"
NEGATIVE_HIT = "negative_hit"
DEFAULT_SCORE_THRESHOLD = 0.35
DEFAULT_CANDIDATE_LIMIT = 5


@dataclass(frozen=True)
class SourceLocator:
    """Positions that already exist on the TextUnit. Never fabricated."""

    text_unit_id: str
    document_id: str
    document_version_id: str
    exact_text: str
    page_start: int | None = None
    page_end: int | None = None
    locator: str | None = None
    section_id: str | None = None
    rects: tuple[dict[str, float], ...] = ()


@dataclass(frozen=True)
class RankedCandidate:
    text_unit_id: str
    exact_text: str
    similarity: float
    polarity: CellPolarity
    source: SourceLocator


@dataclass(frozen=True)
class CellDecision:
    status: CellStatus
    selected: RankedCandidate | None
    candidates: tuple[RankedCandidate, ...]
    threshold: float
    no_hit_reason: str | None = None


@dataclass(frozen=True)
class ColumnSpec:
    column_id: int | None
    title: str
    anchor_set_id: str
    label: str
    polarity: CellPolarity = "positive"
    allow_abstain: bool = False
    abstain_margin: float | None = None
    sort_order: int = 0


@dataclass(frozen=True)
class DocumentRow:
    document_id: str
    document_version_id: str
    title: str
    source_object_id: str | None = None


@dataclass(frozen=True)
class ReviewInputs:
    review_id: int
    customer_id: int
    name: str
    score_threshold: float
    columns: tuple[ColumnSpec, ...]
    documents: tuple[DocumentRow, ...]
    locked_cell_keys: frozenset[tuple[str, int]] = field(default_factory=frozenset)
    embedding_model: str = ""
