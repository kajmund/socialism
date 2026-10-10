"""Per-document examination state. Retrieved is not classified."""

from __future__ import annotations

from dataclasses import dataclass, field

from overgraph_ingest.coverage.proof import ABSENCE, COMPOSITE, EXISTS
from overgraph_ingest.jev.questions import Label

UNEXAMINED = "UNEXAMINED"
RETRIEVED = "RETRIEVED"
NO_EVIDENCE_YET = "NO_EVIDENCE_YET"
EVIDENCE_FOUND = "EVIDENCE_FOUND"
NEEDS_ANALYSIS = "NEEDS_ANALYSIS"
UNRESOLVED = "UNRESOLVED"
VERIFIED_ABSENT = "VERIFIED_ABSENT"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass
class UnitRecord:
    key: str
    predicted: Label | None
    source: str
    hop: str | None = None
    text: str = ""


@dataclass
class DocumentState:
    relative_path: str
    document_units: int
    retrieved: list[UnitRecord] = field(default_factory=list)
    status: str = UNEXAMINED
    hop_attempted: bool = False
    required_parts: tuple[str, ...] = ()

    def classified_keys(self) -> set[str]:
        return {row.key for row in self.retrieved if row.predicted is not None}

    def retrieved_keys(self) -> set[str]:
        return {row.key for row in self.retrieved}

    def yes_count(self) -> int:
        return sum(1 for row in self.retrieved if row.predicted == "YES")

    def uncertain_keys(self) -> list[str]:
        return [row.key for row in self.retrieved if row.predicted == "UNCERTAIN"]

    def classified_count(self) -> int:
        return len(self.classified_keys())

    def parts_found(self) -> int:
        texts = [row.text for row in self.retrieved if row.text]
        return sum(1 for part in self.required_parts if any(part in text for text in texts))

    def parts_complete(self) -> bool:
        return bool(self.required_parts) and self.parts_found() == len(self.required_parts)


def resolve_status(
    doc: DocumentState,
    *,
    proof_kind: str,
    budget: int | None = None,
) -> str:
    classified = [row for row in doc.retrieved if row.predicted is not None]
    if not doc.retrieved:
        return UNEXAMINED
    if not classified:
        return RETRIEVED
    remaining = doc.document_units - len(classified)
    if proof_kind == EXISTS and doc.yes_count():
        return EVIDENCE_FOUND
    if proof_kind == COMPOSITE and doc.required_parts:
        if doc.parts_complete():
            return EVIDENCE_FOUND
        if doc.yes_count():
            return NEEDS_ANALYSIS
    if proof_kind == COMPOSITE and doc.yes_count() and not doc.hop_attempted:
        return NEEDS_ANALYSIS
    if any(row.predicted == "UNCERTAIN" for row in classified) and not doc.hop_attempted:
        return NEEDS_ANALYSIS
    if doc.yes_count():
        return EVIDENCE_FOUND
    if proof_kind == ABSENCE and remaining <= 0:
        return VERIFIED_ABSENT
    if budget is not None and len(classified) >= budget and remaining > 0:
        return BUDGET_EXHAUSTED
    if classified:
        return NO_EVIDENCE_YET
    return RETRIEVED


def is_open(doc: DocumentState) -> bool:
    return doc.status not in {EVIDENCE_FOUND, VERIFIED_ABSENT, BUDGET_EXHAUSTED}


def is_resolved(doc: DocumentState) -> bool:
    return doc.status in {EVIDENCE_FOUND, VERIFIED_ABSENT}
