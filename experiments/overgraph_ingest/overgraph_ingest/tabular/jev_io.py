"""Jev classify, decide, and answer. Choice only; no invented quotes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from overgraph_ingest.jev.candidates import ClassifiedCandidate
from overgraph_ingest.jev.classify import Judgment, classify_candidates
from overgraph_ingest.jev.client import JevClient, JevError, JevResult
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.navigate import NavOffer
from overgraph_ingest.tabular.present import source_preview, state_unit

ANSWER = "ANSWER"
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class UsageCounter:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, result: JevResult) -> None:
        self.calls += 1
        if result.usage.prompt_tokens is not None:
            self.prompt_tokens += result.usage.prompt_tokens
        if result.usage.completion_tokens is not None:
            self.completion_tokens += result.usage.completion_tokens


@dataclass
class CountingJev:
    inner: JevClient
    usage: UsageCounter = field(default_factory=UsageCounter)

    def ask(
        self,
        *,
        state: object,
        questions: dict[str, object],
        model: str,
        timeout_seconds: float,
    ) -> JevResult:
        result = self.inner.ask(
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self.usage.add(result)
        return result


def classify_units(
    client: JevClient,
    candidates: list[ClassifiedCandidate],
    *,
    question: str,
    model: str,
    timeout_seconds: float,
) -> tuple[list[Judgment], float]:
    return classify_candidates(
        client,
        candidates,
        model=model,
        timeout_seconds=timeout_seconds,
        batch_size=1,
        context="none",
        concurrency=1,
        question=question,
    )


def decide(
    client: JevClient,
    *,
    user_question: str,
    offer: NavOffer,
    examined: list[StoredUnit],
    judgments: list[Judgment],
    model: str,
    timeout_seconds: float,
) -> str:
    choices = {
        ANSWER: "The examined units are enough to answer the user question.",
        UNCERTAIN: "The examined material is insufficient or contradictory.",
        NOT_FOUND: "No relevant information was found in the examined material.",
    }
    for option in offer.options:
        label = (
            f"Read {option.operation} unit. "
            f"clause={option.clause_number or 'none'} "
            f"preview={option.text[:160]}"
        )
        if option.reference:
            label = f"Resolve reference punkt {option.reference}. {label}"
        choices[option.choice_id] = label
    questions = {
        "decision": {
            "type": "choice",
            "instructions": (
                f"{user_question} "
                "Choose ANSWER only if the examined units already answer the question. "
                "Choose a listed hop only for a concrete missing unit. "
                "Do not invent a unit id, clause number, or source position. "
                "If a listed reference report is ABSENT or AMBIGUOUS, do not "
                "substitute another clause."
            ),
            "criteria": choices,
        }
    }
    result = client.ask(
        state={
            "task": "tabular_decide",
            "question": user_question,
            "examined": [
                {
                    "id": unit.key,
                    "text": unit.text,
                    "predicted": next(
                        (
                            item.predicted
                            for item in judgments
                            if item.key == unit.key
                        ),
                        "",
                    ),
                }
                for unit in examined
            ],
            "reference_reports": list(offer.reports),
        },
        questions=questions,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    return _named_choice(result, "decision", set(choices))


P0_STATUS_INSTRUCTIONS = (
    "{question} "
    "Answer only from examined units. "
    "ANSWERED requires choosing a listed excerpt that is an exact substring."
)


P0_STATUS_CRITERIA = {
    ANSWERED: "The examined units answer the question.",
    UNCERTAIN: "The examined material is insufficient or contradictory.",
    NOT_FOUND: "No relevant information was found in the examined material.",
}


def answer_cell(
    client: JevClient,
    *,
    user_question: str,
    examined: list[StoredUnit],
    model: str,
    timeout_seconds: float,
    instructions: str | None = None,
    status_criteria: dict[str, str] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
) -> tuple[str, str, str, str]:
    spans = proposed_spans(examined)
    status_q = {
        "type": "choice",
        "instructions": (instructions or P0_STATUS_INSTRUCTIONS).format(question=user_question),
        "criteria": dict(status_criteria or P0_STATUS_CRITERIA),
    }
    source_criteria = {
        unit.key: source_preview(unit, (structures or {}).get(unit.structure_id))
        for unit in examined
    }
    source_criteria["none"] = "No examined unit answers the question."
    excerpt_criteria = {span["id"]: span["text"] for span in spans}
    excerpt_criteria["none"] = "No listed excerpt answers the question."
    result = client.ask(
        state={
            "task": "tabular_answer",
            "question": user_question,
            "units": [
                state_unit(unit, (structures or {}).get(unit.structure_id))
                for unit in examined
            ],
            "excerpts": spans,
        },
        questions={
            "status": status_q,
            "source": {
                "type": "choice",
                "instructions": "Which examined unit is the source? Pick none if not answering.",
                "criteria": source_criteria,
            },
            "excerpt": {
                "type": "choice",
                "instructions": "Pick a listed excerpt. Do not invent text.",
                "criteria": excerpt_criteria,
            },
        },
        model=model,
        timeout_seconds=timeout_seconds,
    )
    status = _named_choice(result, "status", {ANSWERED, UNCERTAIN, NOT_FOUND})
    source = _named_choice(result, "source", set(source_criteria))
    excerpt_id = _named_choice(result, "excerpt", set(excerpt_criteria))
    excerpt = next((span["text"] for span in spans if span["id"] == excerpt_id), "")
    return status, source, excerpt, excerpt_id


MULTI_SLOTS = 5
SLOT_IDS = tuple(f"answer_{index}" for index in range(1, MULTI_SLOTS + 1))
MULTI_STATUS_INSTRUCTIONS = (
    "{question} "
    "Answer only from examined units. "
    "ANSWERED requires choosing one or more listed excerpts that are exact substrings. "
    "List every distinct answer. Pick none for unused slots. "
    "Do not invent text. Do not repeat the same excerpt."
)


def answer_cell_multi(
    client: JevClient,
    *,
    user_question: str,
    examined: list[StoredUnit],
    model: str,
    timeout_seconds: float,
    status_criteria: dict[str, str] | None = None,
) -> tuple[str, list[tuple[str, str, str]]]:
    spans = proposed_spans(examined)
    excerpt_criteria = {span["id"]: span["text"] for span in spans}
    excerpt_criteria["none"] = "No listed excerpt answers the question."
    questions: dict[str, object] = {
        "status": {
            "type": "choice",
            "instructions": MULTI_STATUS_INSTRUCTIONS.format(question=user_question),
            "criteria": dict(status_criteria or P0_STATUS_CRITERIA),
        }
    }
    for index, slot in enumerate(SLOT_IDS, start=1):
        questions[slot] = {
            "type": "choice",
            "instructions": (
                f"Answer {index}. Pick a listed excerpt for a distinct answer. "
                "Pick none if there is no further distinct answer. Do not invent text."
            ),
            "criteria": excerpt_criteria,
        }
    result = client.ask(
        state={
            "task": "tabular_answer_multi",
            "question": user_question,
            "units": [state_unit(unit) for unit in examined],
            "excerpts": spans,
        },
        questions=questions,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    status = _named_choice(result, "status", {ANSWERED, UNCERTAIN, NOT_FOUND})
    pairs: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for slot in SLOT_IDS:
        excerpt_id = _named_choice(result, slot, set(excerpt_criteria))
        if excerpt_id == "none":
            continue
        span = next(item for item in spans if item["id"] == excerpt_id)
        if span["text"] in seen:
            continue
        seen.add(span["text"])
        pairs.append((span["unit_id"], span["text"], excerpt_id))
    return status, pairs


def proposed_spans(units: list[StoredUnit]) -> list[dict[str, str]]:
    spans: list[dict[str, str]] = []
    for unit in units:
        parts = [part.strip() for part in SENTENCE_RE.split(unit.text) if part.strip()]
        if unit.text.strip() and unit.text.strip() not in parts and len(unit.text) <= 400:
            parts.append(unit.text.strip())
        if not parts and unit.text.strip():
            parts = [unit.text.strip()]
        for part in parts[:6]:
            spans.append({"id": f"{unit.key}:{len(spans)}", "unit_id": unit.key, "text": part})
    return spans


def _named_choice(result: JevResult, key: str, allowed: set[str]) -> str:
    row = result.answers.get(key)
    if not isinstance(row, dict):
        raise JevError(f"Jev response missing choice for {key}", category="schema_validation")
    choice = str(row.get("choice") or "").strip()
    if choice not in allowed:
        raise JevError(f"invalid Jev choice {choice!r} for {key}", category="schema_validation")
    # `confidence` and `probabilities` stay on the raw row. They must not
    # decide status. Probability P1 rejected that use.
    return choice
