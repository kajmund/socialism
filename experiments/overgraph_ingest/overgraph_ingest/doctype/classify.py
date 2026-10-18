"""One Jev choice per document. Same taxonomy for B and C."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from overgraph_ingest.doctype.taxonomy import (
    DOCUMENT_TYPES,
    TAXONOMY_VERSION,
    TYPE_CRITERIA,
    TYPE_LABELS,
    require_type,
)
from overgraph_ingest.doctype.view import VARIANT_B, VARIANT_C, DocumentView
from overgraph_ingest.jev.client import JevClient, JevError
from overgraph_ingest.jev.questions import parse_confidence

QUESTION_KEY = "document_type"
CLASSIFY_INSTRUCTIONS = (
    "Classify the document's principal function. "
    "Choose exactly one type from the criteria. "
    "The type describes what the document is for, not which clauses it contains. "
    "A consulting or employment agreement that contains a secrecy clause is not an NDA. "
    "A main contract that only mentions data protection is not a DPA. "
    "A later settlement of a dispute about a past termination is not an "
    "employment termination agreement. "
    "If none of the named types fit, choose other."
)

_ALIASES = {
    **{document_type: document_type for document_type in DOCUMENT_TYPES},
    **{label.casefold(): document_type for document_type, label in TYPE_LABELS.items()},
}


@dataclass(frozen=True)
class Classification:
    document_id: str
    relative_path: str
    document_type: str
    method: str
    variant: str
    model: str
    score: float | None
    taxonomy_version: str
    distribution: dict[str, object] | None
    latency_ms: float
    jev_calls: int


def classify_question() -> dict[str, object]:
    return {
        "type": "choice",
        "instructions": CLASSIFY_INSTRUCTIONS,
        "criteria": dict(TYPE_CRITERIA),
    }


def classify_jev(
    client: JevClient,
    view: DocumentView,
    *,
    wide: bool,
    model: str,
    timeout_seconds: float,
) -> Classification:
    variant = VARIANT_C if wide else VARIANT_B
    result = client.ask(
        state=view.c_state() if wide else view.a_state(),
        questions={QUESTION_KEY: classify_question()},
        model=model,
        timeout_seconds=timeout_seconds,
    )
    document_type, score, distribution = parse_document_type(result.answers)
    return Classification(
        document_id=view.document_id,
        relative_path=view.relative_path,
        document_type=document_type,
        method="jev",
        variant=variant,
        model=str(result.model or model),
        score=score,
        taxonomy_version=TAXONOMY_VERSION,
        distribution=distribution,
        latency_ms=result.latency_ms,
        jev_calls=1,
    )


def parse_document_type(
    answers: dict[str, Any],
    key: str = QUESTION_KEY,
) -> tuple[str, float | None, dict[str, object] | None]:
    row = answers.get(key)
    if not isinstance(row, dict):
        raise JevError(f"Jev response missing choice for {key}", category="schema_validation")
    raw = str(row.get("choice") or "").strip()
    document_type = _ALIASES.get(raw.casefold())
    if document_type is None:
        raise JevError(f"invalid Jev document type {raw!r}", category="schema_validation")
    distribution = _distribution(row)
    return require_type(document_type), parse_confidence(row, key=key), distribution


def _distribution(row: dict[str, Any]) -> dict[str, object] | None:
    for name in ("distribution", "scores", "probabilities"):
        value = row.get(name)
        if isinstance(value, dict):
            return {str(key): value[key] for key in value}
    return None
