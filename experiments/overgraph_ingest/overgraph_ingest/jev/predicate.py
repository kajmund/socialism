"""Jev extracts a typed predicate. It does not decide SUPPORTED."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from overgraph_ingest.coverage.proof_logic import split_predications
from overgraph_ingest.jev.client import JevError

OPERATORS = ("does_not_apply", "applies", "inverted", "none")
OBJECTS = ("secrecy_breach", "other", "none")
PREDICATE_TASK = (
    "Extract the liability-cap / confidentiality predicate expressed in the "
    "evidence. Do not decide SUPPORTED or EVIDENCE_FOUND."
)


@dataclass(frozen=True)
class Predicate:
    subject: str
    operator: str
    object: str
    excerpt: str
    start: int
    end: int
    source_text: str
    unit_id: str


def candidate_spans(evidence: dict[str, object]) -> list[dict[str, str]]:
    """Code proposes spans. Jev only picks. It cannot generate text."""
    kind = str(evidence.get("kind") or "passage")
    if kind == "resolved_reference":
        return [
            {"id": "span_0", "text": str(evidence["source_text"]), "role": "source"},
            {"id": "span_1", "text": str(evidence["target_text"]), "role": "target"},
        ]
    if kind == "labeled_units":
        return [
            {"id": f"span_{index}", "text": str(unit["text"]), "role": f"unit_{unit['id']}"}
            for index, unit in enumerate(list(evidence.get("units") or []))
        ]
    parts = split_predications(str(evidence.get("text") or ""))
    texts = list(parts) if parts else [str(evidence.get("text") or "")]
    return [{"id": f"span_{index}", "text": text, "role": "passage"} for index, text in enumerate(texts)]


def predicate_questions(candidates: list[dict[str, str]]) -> dict[str, Any]:
    span_criteria = {row["id"]: row["text"] for row in candidates}
    span_criteria["none"] = "No candidate states a liability-cap and secrecy relation."
    return {
        "operator": {
            "type": "choice",
            "instructions": (
                f"{PREDICATE_TASK} "
                "Which operator holds between the liability cap and confidentiality breach? "
                "Judge only the supplied evidence. inverted means a general negation is "
                "itself excepted for secrecy, so the cap still covers secrecy breach."
            ),
            "criteria": {
                "does_not_apply": "The cap does not apply to secrecy breach.",
                "applies": "The cap applies to secrecy breach.",
                "inverted": (
                    "A general 'does not apply' is excepted for secrecy; "
                    "the cap still covers secrecy breach."
                ),
                "none": "The evidence does not express that relation.",
            },
        },
        "object": {
            "type": "choice",
            "instructions": (
                "What is the object of that liability-cap operator? "
                "other includes intent, GDPR, a numbered clause, or indirect damage."
            ),
            "criteria": {
                "secrecy_breach": "Confidentiality or secrecy breach.",
                "other": "Some other situation.",
                "none": "No such object is stated.",
            },
        },
        "span": {
            "type": "choice",
            "instructions": (
                "Which candidate is the exact source span of that predicate? "
                "Pick none if no candidate states it. Do not join labeled units."
            ),
            "criteria": span_criteria,
        },
    }


def parse_predicate(
    answers: dict[str, Any],
    candidates: list[dict[str, str]],
    source_text: str,
) -> Predicate:
    operator = _choice(answers, "operator", OPERATORS)
    obj = _choice(answers, "object", OBJECTS)
    allowed = tuple(row["id"] for row in candidates) + ("none",)
    span_id = _choice(answers, "span", allowed)
    chosen = next((row for row in candidates if row["id"] == span_id), None)
    excerpt = "" if chosen is None else chosen["text"]
    start = source_text.find(excerpt) if excerpt else -1
    end = start + len(excerpt) if start >= 0 else -1
    return Predicate(
        subject="liability_cap",
        operator=operator,
        object=obj,
        excerpt=excerpt,
        start=start,
        end=end,
        source_text=source_text,
        unit_id="none" if chosen is None else chosen["id"],
    )


def _choice(answers: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    row = answers.get(key)
    if not isinstance(row, dict):
        raise JevError(f"Jev response missing choice for {key}", category="schema_validation")
    choice = str(row.get("choice") or "").strip()
    if choice not in allowed:
        raise JevError(f"invalid Jev {key} {choice!r}", category="schema_validation")
    return choice
