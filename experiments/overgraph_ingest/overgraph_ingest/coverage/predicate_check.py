"""Admit a Jev predicate only as far as structure can check. Not a controller."""

from __future__ import annotations

from overgraph_ingest.coverage.evidence import validate_span
from overgraph_ingest.coverage.proof_logic import CLAIM_FORM, INVERTED_FORM, UNDECIDED_FORM, read_logic
from overgraph_ingest.jev.predicate import Predicate

VERIFIED = "verified"
PROPOSED = "proposed"
INSUFFICIENT = "insufficient"


def check_predicate(pred: Predicate) -> dict[str, object]:
    """A proposed paraphrase is not EVIDENCE_FOUND."""
    form = read_logic(pred.excerpt).form if pred.excerpt else UNDECIDED_FORM
    if pred.operator == "none" or pred.object == "none" or not pred.excerpt:
        return _result(INSUFFICIENT, False, "no_predicate", form)
    if not validate_span(pred.unit_id, pred.source_text, pred.excerpt).validated:
        return _result(INSUFFICIENT, False, "span_not_in_source", form)
    if pred.operator == "does_not_apply" and pred.object == "secrecy_breach":
        if form == INVERTED_FORM:
            return _result(INSUFFICIENT, False, "structure_inverted", form)
        if form == CLAIM_FORM:
            return _result(VERIFIED, True, "structure_confirms", form)
        return _result(PROPOSED, False, "paraphrase_unverified", form)
    if pred.operator == "inverted":
        if form == INVERTED_FORM:
            return _result(VERIFIED, False, "inverted_confirmed", form)
        return _result(PROPOSED, False, "inverted_unverified", form)
    if pred.operator == "applies":
        if form == CLAIM_FORM:
            return _result(INSUFFICIENT, False, "structure_contradicts", form)
        return _result(PROPOSED, False, "applies_unverified", form)
    return _result(INSUFFICIENT, False, "other_object", form)


def _result(tier: str, found: bool, reason: str, form: str) -> dict[str, object]:
    return {"tier": tier, "evidence_found": found, "reason": reason, "form": form}
