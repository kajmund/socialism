"""Per-document examination state. Retrieved is not classified."""

from __future__ import annotations

from dataclasses import dataclass, field

from overgraph_ingest.coverage.proof import ABSENCE, COMPOSITE, EXISTS
from overgraph_ingest.coverage.proof_gate import admit_complete
from overgraph_ingest.coverage.proof_link import (
    LINKED_RELATION,
    NEEDS_NAVIGATION,
    PROOF_LINK,
    evaluate_passage,
    evaluate_passages,
    resolve_reference,
)
from overgraph_ingest.coverage.proof_relation import (
    COMPLETE_IN_UNIT,
    PROOF_CURRENT,
    PROOF_RELATION,
    UNRESOLVED_REFERENCE,
    relation_status,
)
from overgraph_ingest.jev.questions import Label

UNEXAMINED = "UNEXAMINED"
RETRIEVED = "RETRIEVED"
NO_EVIDENCE_YET = "NO_EVIDENCE_YET"
EVIDENCE_FOUND = "EVIDENCE_FOUND"
NEEDS_ANALYSIS = "NEEDS_ANALYSIS"
UNRESOLVED = "UNRESOLVED"
VERIFIED_ABSENT = "VERIFIED_ABSENT"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
UNDECIDED = "UNDECIDED"


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
    gate_block: dict[str, object] | None = None

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
    proof_rule: str = PROOF_CURRENT,
    proof_gate: bool = False,
) -> str:
    classified = [row for row in doc.retrieved if row.predicted is not None]
    if not doc.retrieved:
        return UNEXAMINED
    if not classified:
        return RETRIEVED
    remaining = doc.document_units - len(classified)
    if proof_kind == EXISTS and doc.yes_count():
        return EVIDENCE_FOUND
    if proof_kind == COMPOSITE and proof_rule == PROOF_LINK:
        status = _resolve_link(doc, classified, remaining=remaining, budget=budget)
        return _apply_gate(doc, status, classified, enabled=proof_gate)
    if proof_kind == COMPOSITE and proof_rule == PROOF_RELATION:
        status = _resolve_relation(doc, classified, remaining=remaining, budget=budget)
        return _apply_gate(doc, status, classified, enabled=proof_gate)
    if proof_kind == COMPOSITE and doc.required_parts:
        if doc.parts_complete():
            return _apply_gate(doc, EVIDENCE_FOUND, classified, enabled=proof_gate)
        if doc.yes_count():
            return NEEDS_ANALYSIS
    if proof_kind == COMPOSITE and doc.yes_count() and not doc.hop_attempted:
        return NEEDS_ANALYSIS
    if any(row.predicted == "UNCERTAIN" for row in classified) and not doc.hop_attempted:
        return NEEDS_ANALYSIS
    if doc.yes_count():
        return _apply_gate(doc, EVIDENCE_FOUND, classified, enabled=proof_gate)
    if proof_kind == ABSENCE and remaining <= 0:
        return VERIFIED_ABSENT
    if budget is not None and len(classified) >= budget and remaining > 0:
        return BUDGET_EXHAUSTED
    if classified:
        return NO_EVIDENCE_YET
    return RETRIEVED


def _resolve_link(
    doc: DocumentState,
    classified: list[UnitRecord],
    *,
    remaining: int,
    budget: int | None,
) -> str:
    texts = [row.text for row in classified if row.text]
    judged = evaluate_passages(texts)
    if judged["status"] == LINKED_RELATION or _resolved_reference(classified):
        return EVIDENCE_FOUND
    needs_hop = judged["status"] == NEEDS_NAVIGATION or any(
        row.predicted == "UNCERTAIN" for row in classified
    )
    if needs_hop and not doc.hop_attempted:
        return NEEDS_ANALYSIS
    if budget is not None and len(classified) >= budget and remaining > 0:
        return BUDGET_EXHAUSTED
    if remaining <= 0 or classified:
        return NO_EVIDENCE_YET
    return RETRIEVED


def _resolved_reference(classified: list[UnitRecord]) -> bool:
    sources = [row for row in classified if row.text]
    for source in sources:
        if evaluate_passage(source.text)["status"] != NEEDS_NAVIGATION:
            continue
        for target in sources:
            if target.key == source.key:
                continue
            if resolve_reference(source.text, target.text)["status"] == LINKED_RELATION:
                return True
    return False


def _resolve_relation(
    doc: DocumentState,
    classified: list[UnitRecord],
    *,
    remaining: int,
    budget: int | None,
) -> str:
    texts = [row.text for row in classified if row.text]
    status = relation_status(texts=texts, required_parts=doc.required_parts)
    if status == COMPLETE_IN_UNIT:
        return EVIDENCE_FOUND
    needs_hop = status in {UNRESOLVED_REFERENCE} or bool(doc.required_parts) or any(
        row.predicted == "UNCERTAIN" for row in classified
    )
    if needs_hop and not doc.hop_attempted:
        return NEEDS_ANALYSIS
    if budget is not None and len(classified) >= budget and remaining > 0:
        return BUDGET_EXHAUSTED
    if remaining <= 0:
        return NO_EVIDENCE_YET
    if classified:
        return NO_EVIDENCE_YET
    return RETRIEVED


def _apply_gate(
    doc: DocumentState,
    status: str,
    classified: list[UnitRecord],
    *,
    enabled: bool,
) -> str:
    if not enabled or status != EVIDENCE_FOUND:
        if not enabled:
            doc.gate_block = None
        return status
    admission = admit_complete(
        yes_texts=[row.text for row in classified if row.predicted == "YES" and row.text],
        hop_pairs=[
            (source.text, target.text)
            for source in classified
            if source.text
            for target in classified
            if target.hop and target.text and target.key != source.key
        ],
    )
    if not admission["blocked"]:
        doc.gate_block = None
        return EVIDENCE_FOUND
    doc.gate_block = admission
    return UNDECIDED


def is_open(doc: DocumentState) -> bool:
    return doc.status not in {EVIDENCE_FOUND, VERIFIED_ABSENT, BUDGET_EXHAUSTED, UNDECIDED}


def is_resolved(doc: DocumentState) -> bool:
    return doc.status in {EVIDENCE_FOUND, VERIFIED_ABSENT}
