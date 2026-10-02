"""Bounded, lossless passage experiments. No production ingestion or retrieval."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.research.assessment import AssessableEvidence
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from tests.research_reuse.jev_passages import ScreenRequest

CRITERIA: tuple[str, str] = ("relevant_to_question", "directly_supports_answer")


@dataclass(frozen=True)
class Passage:
    evidence_id: str
    field: str
    start: int
    end: int
    context_start: int
    context_end: int
    text: str
    row: dict

    @property
    def id(self) -> str:
        return f"{self.evidence_id}:{self.field}:{self.start}:{self.end}"


def split(item: AssessableEvidence, *, field: str, chars: int = 1200) -> list[Passage]:
    if chars < 200 or field not in {"excerpt", "source"}:
        raise ValueError("Invalid passage field or size")
    text = item.legal_result.raw_text if field == "source" and item.legal_result else item.excerpt or ""
    selected_field = "legal_result.raw_text" if field == "source" and item.legal_result else "excerpt"
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    output = []
    for start in range(0, max(1, len(text)), chars):
        end = min(start + chars, len(text))
        left, right = max(0, start - 160), min(len(text), end + 160)
        row = {
            "evidence_id": item.evidence_id, "title": item.title, "source_type": item.source_type,
            "content_hash": item.content_hash, "source_text_sha256": source_hash,
            "field": selected_field, "start": start, "end": end, "context_start": left,
            "context_end": right, "excerpt": text[left:right],
        }
        passage = Passage(item.evidence_id, selected_field, start, end, left, right, text[start:end], row)
        output.append(passage)
    if "".join(p.text for p in output) != text:
        raise ValueError("Passages do not reconstruct the exact original text")
    return output


def request(objective: str, passages: Sequence[Passage]) -> ScreenRequest:
    rows = [{**p.row, "passage_id": p.id} for p in passages]
    state = {"objective": objective, "evidence": rows}
    questions, bindings = {}, {}
    for index, passage in enumerate(passages):
        for criterion in CRITERIA:
            key = f"p{index}_{criterion}"
            schema = EVIDENCE_SCREEN_QUESTIONS[criterion]
            questions[key] = {**schema, "instructions": {
                "task": schema["instructions"], "passage_id": passage.id,
            }}
            bindings[key] = (passage.id, criterion)
    return ScreenRequest(state, questions, bindings)


def plan(
    items: Sequence[AssessableEvidence], *, objective: str, field: str, max_state_chars: int,
) -> tuple[list[ScreenRequest], list[Passage]]:
    if len({i.evidence_id for i in items}) != len(items):
        raise ValueError("Passage evidence IDs must be unique")
    passages = [p for item in items for p in split(item, field=field)]
    batches, pending = [], []
    for passage in passages:
        candidate = request(objective, [*pending, passage])
        if pending and (len(json.dumps(candidate.state, ensure_ascii=False)) > max_state_chars
                or len(candidate.questions) > 16):
            batches.append(request(objective, pending))
            pending = []
        pending.append(passage)
        if len(json.dumps(request(objective, pending).state, ensure_ascii=False)) > max_state_chars:
            raise ValueError("A complete passage exceeds the explicit state budget")
    if pending:
        batches.append(request(objective, pending))
    return batches, passages


def aggregate(scores: dict, passages: Sequence[Passage]) -> dict:
    """Keep both judgments from one best passage; no document sufficiency decision."""
    if set(scores) != {p.id for p in passages}:
        raise ValueError("Passage results are missing or contain unexpected IDs")
    output: dict[str, dict[str, float]] = {}
    for p in passages:
        candidate = scores[p.id]
        previous = output.get(p.evidence_id)
        if previous is None or joint(candidate) > joint(previous):
            output[p.evidence_id] = dict(candidate)
    return output


def joint(scores: dict) -> float:
    return min(scores["relevant_to_question"] / 0.8, scores["directly_supports_answer"] / 0.5)


def contradiction_requests(items: Sequence[AssessableEvidence], objective: str) -> list[ScreenRequest]:
    if len(items) != 2:
        raise ValueError("Explicit contradiction controls require exactly two candidate facts")
    schema = EVIDENCE_SCREEN_QUESTIONS["contradicts_current_evidence"]
    rows = [{"evidence_id": i.evidence_id, "excerpt": i.excerpt} for i in items]
    return [ScreenRequest(
        state={"objective": objective, "evidence": rows[index],
            "other_supplied_facts": [rows[1 - index]]},
        questions={"contradicts_current_evidence": schema},
        bindings={"contradicts_current_evidence": (items[index].evidence_id, "contradicts_current_evidence")},
    ) for index in range(2)]
