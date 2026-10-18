"""Relation polarity and scope. Not a parser, not a gate, not Coverage v3."""

from __future__ import annotations

import re
from dataclasses import dataclass

from overgraph_ingest.coverage.evidence import validate_span
from overgraph_ingest.coverage.proof_gate import POLARITY_UNRESOLVED, polarity_status
from overgraph_ingest.coverage.proof_link import LINKED_RELATION, evaluate_passage
from overgraph_ingest.coverage.proof_relation import COMPONENT_PATTERNS

CLAIM = "liability_cap_excludes_confidentiality_breach"
CLAIM_FORM = "liability_cap → does_not_apply → secrecy_breach"
INVERTED_FORM = "liability_cap → does_not_apply → other → except secrecy_breach"
APPLIES_FORM = "liability_cap → applies → secrecy_breach"
UNDECIDED_FORM = "undecided"
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Predication:
    text: str
    form: str


@dataclass(frozen=True)
class RelationLogic:
    claim: str
    form: str
    predications: tuple[Predication, ...]
    relation_validated: bool


def split_predications(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in SENTENCE_RE.split(text.strip()) if part.strip())


def classify_predication(text: str) -> str:
    """Stacked polarity is inverted even when LINK_RE also matches that sentence."""
    secrecy = bool(COMPONENT_PATTERNS["secrecy_breach"].search(text))
    if polarity_status(text) == POLARITY_UNRESOLVED and secrecy:
        return INVERTED_FORM
    if evaluate_passage(text)["status"] == LINKED_RELATION:
        return CLAIM_FORM
    return UNDECIDED_FORM


def read_logic(text: str) -> RelationLogic:
    predications = tuple(
        Predication(sentence, classify_predication(sentence))
        for sentence in split_predications(text)
    )
    forms = [row.form for row in predications]
    if CLAIM_FORM in forms:
        form = CLAIM_FORM
    elif INVERTED_FORM in forms:
        form = INVERTED_FORM
    else:
        form = UNDECIDED_FORM
    return RelationLogic(
        claim=CLAIM,
        form=form,
        predications=predications,
        relation_validated=form == CLAIM_FORM,
    )


def judge_invariants(
    text: str,
    *,
    excerpt: str | None = None,
    jev_yes: bool = False,
) -> dict[str, object]:
    """Span validation and relation validation are separate. Quote plus YES is not proof."""
    logic = read_logic(text)
    judged = evaluate_passage(text)
    quote = excerpt if excerpt is not None else judged["linked_span"] or ""
    span = validate_span("unit", text, str(quote))
    return {
        "claim": CLAIM,
        "form": logic.form,
        "span_validated": span.validated,
        "relation_validated": logic.relation_validated,
        "quote_and_yes": span.validated and jev_yes,
        "both_invariants": span.validated and logic.relation_validated,
        "predications": [{"text": row.text, "form": row.form} for row in logic.predications],
    }
