"""Jev proof evaluation. Separate from classify. One judgment per prompt."""

from __future__ import annotations

from typing import Any, Literal

from overgraph_ingest.jev.client import JevError

ProofLabel = Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]
PROOF_LABELS = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
PROOF_QUESTION = (
    "Styrker den markerade evidensen uttryckligen att ansvarsbegränsningen "
    "inte gäller vid brott mot sekretessförpliktelser?"
)


def proof_choice_question() -> dict[str, Any]:
    return {
        "type": "choice",
        "instructions": (
            f"{PROOF_QUESTION} "
            "Judge only the supplied evidence object. "
            "Do not invent a relation from separate labeled units. "
            "If kind is resolved_reference, the target may only resolve the "
            "reference in the source; do not use any other text. "
            "SUPPORTED only if the evidence itself states that a liability cap "
            "does not apply to confidentiality or secrecy breach. "
            "CONTRADICTED if the evidence states the opposite relation. "
            "INSUFFICIENT if the evidence is not enough. "
            "Do not drop INSUFFICIENT; it is a valid outcome."
        ),
        "criteria": {
            "SUPPORTED": (
                "The evidence itself states that a liability cap does not apply "
                "to confidentiality or secrecy breach."
            ),
            "CONTRADICTED": (
                "The evidence states the opposite: the cap applies to secrecy "
                "breach, or secrecy is not carved out."
            ),
            "INSUFFICIENT": (
                "The evidence does not establish the relation and does not "
                "clearly state the opposite."
            ),
        },
    }


def parse_proof_choice(answers: dict[str, Any], key: str) -> tuple[ProofLabel, float | None]:
    row = answers.get(key)
    if not isinstance(row, dict):
        raise JevError(f"Jev response missing choice for {key}", category="schema_validation")
    choice = str(row.get("choice") or "").strip().upper()
    if choice not in PROOF_LABELS:
        raise JevError(f"invalid Jev proof choice {choice!r} for {key}", category="schema_validation")
    confidence = row.get("confidence")
    parsed = None if confidence is None else float(confidence)
    if parsed is not None and not 0.0 <= parsed <= 1.0:
        raise JevError(f"Jev confidence for {key} is out of range", category="schema_validation")
    return choice, parsed


def evidence_passage(text: str) -> dict[str, str]:
    return {"kind": "passage", "text": text}


def evidence_resolved(source: str, target: str) -> dict[str, str]:
    return {
        "kind": "resolved_reference",
        "source_text": source,
        "target_text": target,
    }


def evidence_units(texts: list[str]) -> dict[str, object]:
    return {
        "kind": "labeled_units",
        "units": [{"id": chr(65 + index), "text": text} for index, text in enumerate(texts)],
    }
