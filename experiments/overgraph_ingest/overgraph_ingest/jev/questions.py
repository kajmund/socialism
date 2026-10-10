"""Choice classification for automatic / tacit renewal. UNCERTAIN is first-class."""

from __future__ import annotations

from typing import Any, Literal

from overgraph_ingest.jev.client import JevError

Label = Literal["YES", "NO", "UNCERTAIN"]
LABELS = ("YES", "NO", "UNCERTAIN")

CLASSIFY_QUESTION = (
    "Innehåller texten en bestämmelse där avtalet förlängs automatiskt utan ett "
    "nytt uttryckligt godkännande från båda parterna?"
)


def choice_question(question: str) -> dict[str, Any]:
    return {
        "type": "choice",
        "instructions": (
            f"{question} "
            "Classify only the candidate `text` field. "
            "parent_title, parent_text, previous_text, and next_text are supporting "
            "context for that candidate and must not be judged as if they were the candidate. "
            "YES only if the candidate text itself contains the provision asked about. "
            "NO if it does not. If the candidate text is not enough to decide, "
            "choose UNCERTAIN. Do not drop UNCERTAIN; it is a valid outcome."
        ),
        "criteria": {
            "YES": "The candidate text itself contains the provision asked about.",
            "NO": "The candidate text does not contain that provision.",
            "UNCERTAIN": "The supplied text and context are not enough to decide.",
        },
    }


CHOICE_QUESTION = choice_question(CLASSIFY_QUESTION)


def parse_choice(answers: dict[str, Any], key: str) -> tuple[Label, float | None]:
    row = answers.get(key)
    if not isinstance(row, dict):
        raise JevError(f"Jev response missing choice for {key}", category="schema_validation")
    choice = str(row.get("choice") or "").strip().upper()
    if choice not in LABELS:
        raise JevError(f"invalid Jev choice {choice!r} for {key}", category="schema_validation")
    confidence = row.get("confidence")
    parsed = None if confidence is None else float(confidence)
    if parsed is not None and not 0.0 <= parsed <= 1.0:
        raise JevError(f"Jev confidence for {key} is out of range", category="schema_validation")
    return choice, parsed
