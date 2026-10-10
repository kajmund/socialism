"""Classify frozen candidates. One candidate per prompt; concurrency is parallel calls."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from overgraph_ingest.jev.candidates import ClassifiedCandidate
from overgraph_ingest.jev.client import JevClient, JevError
from overgraph_ingest.jev.questions import CLASSIFY_QUESTION, Label, choice_question, parse_choice

ContextKind = Literal["none", "parent", "adjacent"]

CLASSIFY_CANDIDATES_PER_CALL = 1
DEFAULT_CLASSIFY_CONCURRENCY = 8


@dataclass(frozen=True)
class Judgment:
    key: str
    rank: int
    relative_path: str
    gold_label: str
    expected: Label
    predicted: Label
    confidence: float | None
    latency_ms: float
    call_index: int
    batch_size: int
    error: str | None
    text: str


def classify_candidates(
    client: JevClient,
    candidates: list[ClassifiedCandidate],
    *,
    model: str,
    timeout_seconds: float,
    batch_size: int,
    context: ContextKind,
    concurrency: int = DEFAULT_CLASSIFY_CONCURRENCY,
    allow_prompt_batch: bool = False,
    question: str = CLASSIFY_QUESTION,
) -> tuple[list[Judgment], float]:
    if batch_size < 1:
        raise ValueError("jev batch size must be >= 1")
    if concurrency < 1:
        raise ValueError("jev concurrency must be >= 1")
    if batch_size != CLASSIFY_CANDIDATES_PER_CALL and not allow_prompt_batch:
        raise ValueError(
            "classify takes exactly one candidate per prompt; "
            "parallelise calls instead of batching candidates"
        )
    chunks = [
        (call_index, candidates[start : start + batch_size])
        for call_index, start in enumerate(range(0, len(candidates), batch_size))
    ]
    started = time.perf_counter()
    if concurrency == 1 or len(chunks) <= 1:
        judgments = [
            item
            for call_index, chunk in chunks
            for item in _classify_batch(
                client,
                chunk,
                model=model,
                timeout_seconds=timeout_seconds,
                context=context,
                call_index=call_index,
                question=question,
            )
        ]
        return judgments, time.perf_counter() - started
    by_index: dict[int, list[Judgment]] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _classify_batch,
                client,
                chunk,
                model=model,
                timeout_seconds=timeout_seconds,
                context=context,
                call_index=call_index,
                question=question,
            )
            for call_index, chunk in chunks
        ]
        for (call_index, _chunk), future in zip(chunks, futures, strict=True):
            by_index[call_index] = future.result()
    judgments = [item for call_index, _chunk in chunks for item in by_index[call_index]]
    return judgments, time.perf_counter() - started


def expected_label(gold_label: str) -> Label:
    return "YES" if gold_label == "relevant" else "NO"


def _classify_batch(
    client: JevClient,
    chunk: list[ClassifiedCandidate],
    *,
    model: str,
    timeout_seconds: float,
    context: ContextKind,
    call_index: int,
    question: str,
) -> list[Judgment]:
    questions = {item.key: choice_question(question) for item in chunk}
    state = {
        "task": question,
        "judge": "candidate_text_only",
        "candidates": [_state_row(item, context=context) for item in chunk],
    }
    try:
        result = client.ask(
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except JevError as exc:
        return [
            Judgment(
                key=item.key,
                rank=item.rank,
                relative_path=item.relative_path,
                gold_label=item.gold_label,
                expected=expected_label(item.gold_label),
                predicted="UNCERTAIN",
                confidence=None,
                latency_ms=0.0,
                call_index=call_index,
                batch_size=len(chunk),
                error=f"{exc.category}: {exc}",
                text=item.text,
            )
            for item in chunk
        ]
    per_item = result.latency_ms / max(len(chunk), 1)
    judgments: list[Judgment] = []
    for item in chunk:
        try:
            predicted, confidence = parse_choice(result.answers, item.key)
            error = None
        except JevError as exc:
            predicted = "UNCERTAIN"
            confidence = None
            error = f"{exc.category}: {exc}"
        judgments.append(
            Judgment(
                key=item.key,
                rank=item.rank,
                relative_path=item.relative_path,
                gold_label=item.gold_label,
                expected=expected_label(item.gold_label),
                predicted=predicted,
                confidence=confidence,
                latency_ms=per_item,
                call_index=call_index,
                batch_size=len(chunk),
                error=error,
                text=item.text,
            )
        )
    return judgments


def _state_row(item: ClassifiedCandidate, *, context: ContextKind) -> dict[str, str]:
    row = {"id": item.key, "relative_path": item.relative_path, "text": item.text}
    if context == "parent":
        row["structure_title"] = item.structure_title
        row["parent_title"] = item.parent_title
        row["parent_text"] = item.parent_text
    elif context == "adjacent":
        row["previous_text"] = item.previous_text
        row["next_text"] = item.next_text
    return row
