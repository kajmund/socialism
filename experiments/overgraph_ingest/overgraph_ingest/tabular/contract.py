"""Cell answer contract. Navigation is never itself ANSWERED."""

from __future__ import annotations

from dataclasses import dataclass, field

from overgraph_ingest.coverage.evidence import validate_span
from overgraph_ingest.retrieval.index import StoredUnit

ANSWERED = "ANSWERED"
UNCERTAIN = "UNCERTAIN"
NOT_FOUND = "NOT_FOUND"
STATUSES = frozenset({ANSWERED, UNCERTAIN, NOT_FOUND})


@dataclass(frozen=True)
class SourceRef:
    document_id: str
    unit_id: str
    relative_path: str
    char_start: int | None
    char_end: int | None
    excerpt: str
    clause_number: str
    validated: bool


@dataclass
class CellResult:
    document_id: str
    relative_path: str
    question_id: str
    question: str
    variant: str
    status: str
    answer: str
    source_unit_ids: list[str]
    sources: list[SourceRef]
    navigation_steps: int = 0
    units_examined: int = 0
    jev_calls: int = 0
    cerebras_calls: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    retrieve_seconds: float = 0.0
    classify_seconds: float = 0.0
    navigate_seconds: float = 0.0
    answer_seconds: float = 0.0
    cell_seconds: float = 0.0
    retrieval: dict[str, object] = field(default_factory=dict)
    navigation: list[dict[str, object]] = field(default_factory=list)
    budget_exhausted: bool = False
    notes: str = ""


def source_ref(unit: StoredUnit, excerpt: str, *, clause_number: str = "") -> SourceRef:
    span = validate_span(unit.key, unit.text, excerpt)
    return SourceRef(
        document_id=unit.document_id,
        unit_id=unit.key,
        relative_path=unit.relative_path,
        char_start=None if not span.validated else unit.char_start,
        char_end=None if not span.validated else unit.char_end,
        excerpt=excerpt,
        clause_number=clause_number,
        validated=span.validated,
    )


def require_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"unsupported cell status: {status}")
    return status


def answered_requires_source(result: CellResult) -> None:
    if result.status != ANSWERED:
        return
    if not result.sources:
        raise ValueError("ANSWERED requires at least one source")
    if not any(item.validated for item in result.sources):
        raise ValueError("ANSWERED requires a validated source excerpt")
