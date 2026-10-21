"""Jev verification of a proposed document property.

One document-property pair per call. Candidate TextUnits are presented as
primary evidence (full text + clause heading); Jev chooses a supporting unit.
SUPPORTED requires a grounded source; an ungrounded source is UNDECIDED, and a
provider failure is a technical error, never UNSUPPORTED.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.jev.system import JevClientError, JevSystemOne
from app.services.document_properties.model import (
    SUPPORTED,
    UNDECIDED,
    UNSUPPORTED,
    VERIFICATION_DECISIONS,
    DocumentProperty,
)
from app.services.document_properties.taxonomy import PropertyClass

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")

VERIFY_INSTRUCTIONS = (
    "Judge whether any of the listed clause texts supports the proposed "
    "document property. SUPPORTED only when a clause text itself asserts the "
    "property with the stated polarity. A heading, a cross-reference, or a "
    "permission is not support for an obligation or prohibition. UNSUPPORTED "
    "when no clause asserts the property. UNDECIDED when it is unclear without "
    "more context. Choose the clause excerpt that supports the property for "
    "SUPPORTED; choose none otherwise."
)


@dataclass(frozen=True)
class VerificationOutcome:
    decision: str
    source_unit_key: str | None
    supporting_excerpt: str | None
    source_valid: bool


async def verify_document_property(
    jev: JevSystemOne,
    *,
    prop: DocumentProperty,
    spec: PropertyClass,
    candidate_units: Sequence[object],
    model: str,
    timeout_seconds: float,
) -> VerificationOutcome:
    spans = _spans(candidate_units)
    result = await jev.ask(
        state=_state(prop, spec, candidate_units),
        questions=_questions(spans),
        model=model,
        timeout_seconds=timeout_seconds,
    )
    decision = _parse_decision(result.answers)
    source_id = _parse_source(result.answers, allowed={span["id"] for span in spans} | {"none"})
    source_unit_key, excerpt, source_valid = _ground_source(source_id, spans, candidate_units)
    if decision == SUPPORTED and not source_valid:
        decision = UNDECIDED
    return VerificationOutcome(
        decision=decision,
        source_unit_key=source_unit_key,
        supporting_excerpt=excerpt,
        source_valid=source_valid,
    )


def _state(prop: DocumentProperty, spec: PropertyClass, units: Sequence[object]) -> dict:
    return {
        "task": "document_property_verification",
        "property": {
            "class_id": prop.class_id,
            "label": spec.label,
            "definition": spec.definition,
            "value": prop.value,
            "polarity": prop.polarity,
        },
        "evidence_clauses": [
            {"heading": _heading(unit), "text": unit.text} for unit in units
        ],
    }


def _questions(spans: list[dict]) -> dict:
    return {
        "verdict": {
            "type": "choice",
            "instructions": VERIFY_INSTRUCTIONS,
            "criteria": {
                SUPPORTED: "A clause asserts the property with the stated polarity.",
                UNSUPPORTED: "No clause asserts the property.",
                UNDECIDED: "Unclear without more context.",
            },
        },
        "source": {
            "type": "choice",
            "instructions": "Pick the clause excerpt that supports the property, or none.",
            "criteria": {span["id"]: span["text"] for span in spans}
            | {"none": "No listed excerpt supports the property."},
        },
    }


def _spans(units: Sequence[object]) -> list[dict]:
    spans: list[dict] = []
    for unit in units:
        parts = [part.strip() for part in _SENTENCE_BOUNDARY.split(unit.text) if part.strip()]
        if unit.text.strip() and unit.text.strip() not in parts and len(unit.text) <= 400:
            parts.append(unit.text.strip())
        if not parts and unit.text.strip():
            parts = [unit.text.strip()]
        for part in parts[:6]:
            spans.append({"id": f"{unit.id}:{len(spans)}", "unit_id": unit.id, "text": part})
    return spans


def _parse_decision(answers: dict) -> str:
    row = answers.get("verdict")
    choice = row.get("choice") if isinstance(row, dict) else None
    if not isinstance(choice, str) or choice not in VERIFICATION_DECISIONS:
        raise JevClientError("Jev response has invalid verdict", category="schema_validation")
    return choice


def _parse_source(answers: dict, *, allowed: set[str]) -> str:
    row = answers.get("source")
    choice = row.get("choice") if isinstance(row, dict) else None
    if not isinstance(choice, str) or choice not in allowed:
        raise JevClientError("Jev response has invalid source", category="schema_validation")
    return choice


def _ground_source(
    source_id: str,
    spans: list[dict],
    units: Sequence[object],
) -> tuple[str | None, str | None, bool]:
    if source_id == "none":
        return None, None, False
    span = next((item for item in spans if item["id"] == source_id), None)
    if span is None:
        return None, None, False
    unit = next((item for item in units if item.id == span["unit_id"]), None)
    if unit is None or span["text"] not in unit.text:
        return str(span["unit_id"]), str(span["text"]), False
    return str(span["unit_id"]), str(span["text"]), True


def _heading(unit: object) -> str:
    title = getattr(unit, "section_title", None)
    if title is not None:
        return str(title)
    section = getattr(unit, "section", None)
    title = getattr(section, "title", None) if section is not None else None
    return str(title or "")
