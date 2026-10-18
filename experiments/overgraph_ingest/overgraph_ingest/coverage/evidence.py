"""Source-grounded evidence proof. Not a Coverage v3 controller."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.coverage.proof_link import (
    LINKED_RELATION,
    NEEDS_NAVIGATION,
    NOT_GROUNDED,
    evaluate_passage,
    resolve_reference,
)

CLAIM = "liability_cap_excludes_confidentiality_breach"
SUPPORTED = "SUPPORTED"
CONTRADICTED = "CONTRADICTED"
UNDECIDED = "UNDECIDED"
PROOF_STATUSES = (SUPPORTED, CONTRADICTED, UNDECIDED)


@dataclass(frozen=True)
class EvidenceSpan:
    unit_id: str
    start: int
    end: int
    text: str
    source_text: str
    validated: bool


@dataclass(frozen=True)
class EvidenceProof:
    claim: str
    status: str
    spans: tuple[EvidenceSpan, ...]
    references: tuple[dict[str, object], ...]
    relation_support: str


def validate_span(unit_id: str, source_text: str, excerpt: str) -> EvidenceSpan:
    """A span must be an exact substring of the source unit. Not a generated quote."""
    if not excerpt:
        return EvidenceSpan(unit_id, -1, -1, excerpt, source_text, False)
    start = source_text.find(excerpt)
    if start < 0:
        return EvidenceSpan(unit_id, -1, -1, excerpt, source_text, False)
    return EvidenceSpan(unit_id, start, start + len(excerpt), excerpt, source_text, True)


def ground_unit(unit_id: str, source_text: str) -> tuple[EvidenceSpan | None, str]:
    judged = evaluate_passage(source_text)
    if judged["status"] != LINKED_RELATION or not judged["linked_span"]:
        return None, str(judged["status"])
    span = validate_span(unit_id, source_text, str(judged["linked_span"]))
    if not span.validated:
        return None, NOT_GROUNDED
    return span, LINKED_RELATION


def build_proof(
    units: list[tuple[str, str]],
    *,
    hops: list[tuple[str, str, str, str]] | None = None,
    claim: str = CLAIM,
) -> EvidenceProof:
    """Build a proof from unit texts. Hops may resolve a reference; they cannot invent one."""
    spans: list[EvidenceSpan] = []
    supports: list[str] = []
    for unit_id, text in units:
        span, support = ground_unit(unit_id, text)
        supports.append(support)
        if span is not None:
            spans.append(span)
    references = []
    for source_id, source_text, target_id, target_text in hops or ():
        resolved = resolve_reference(source_text, target_text)
        source_judged = evaluate_passage(source_text)
        references.append(
            {
                "source_unit_id": source_id,
                "target_unit_id": target_id,
                "reference": source_judged.get("reference"),
                "referent_matches": resolved.get("referent_matches"),
                "status": resolved.get("status"),
            }
        )
        if source_judged["status"] == LINKED_RELATION:
            continue
        if resolved.get("status") == LINKED_RELATION and resolved.get("grounding_passage"):
            grounding = str(resolved["grounding_passage"])
            for unit_id, text in ((source_id, source_text), (target_id, target_text)):
                span = validate_span(unit_id, text, grounding)
                if span.validated:
                    spans.append(span)
                    break
    if spans:
        status = SUPPORTED
        relation_support = LINKED_RELATION
    elif any(item.get("status") == NEEDS_NAVIGATION for item in references) or NEEDS_NAVIGATION in supports:
        status = UNDECIDED
        relation_support = NEEDS_NAVIGATION
    else:
        status = UNDECIDED
        relation_support = NOT_GROUNDED
    return EvidenceProof(
        claim=claim,
        status=status,
        spans=tuple(spans),
        references=tuple(references),
        relation_support=relation_support,
    )


def admit_evidence_found(proof: EvidenceProof) -> bool:
    """EVIDENCE_FOUND requires a validated proof of the requested relation."""
    if proof.claim != CLAIM or proof.status != SUPPORTED:
        return False
    if not proof.spans or not all(span.validated for span in proof.spans):
        return False
    return all(span.text and span.text in span.source_text for span in proof.spans)


def proof_payload(proof: EvidenceProof) -> dict[str, object]:
    return {
        "claim": proof.claim,
        "status": proof.status,
        "relation_support": proof.relation_support,
        "spans": [
            {
                "unit_id": span.unit_id,
                "start": span.start,
                "end": span.end,
                "text": span.text,
                "validated": span.validated,
            }
            for span in proof.spans
        ],
        "references": list(proof.references),
        "evidence_found": admit_evidence_found(proof),
    }
