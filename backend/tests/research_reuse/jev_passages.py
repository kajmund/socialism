"""Strict replay experiment; never called by production research."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

from app.jev.system import JevClientError, JevSystemOne, parse_noul
from app.services.research.assessment import AssessableEvidence
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.fast_state import compact_evidence_item_state
from tests.research_reuse.snapshots import digest


@dataclass(frozen=True)
class ScreenRequest:
    state: dict[str, Any]
    questions: dict[str, Any]
    bindings: dict[str, tuple[str, str]]


def full_row(item: AssessableEvidence, objective: str) -> dict:
    compact, _, _ = compact_evidence_item_state(
        objective=objective, item=item, max_state_chars=6000,
    )
    row = dict(compact["evidence"])
    row["excerpt"] = item.excerpt
    row["legal_result"] = item.legal_result.model_dump(mode="json") if item.legal_result else None
    row["claims"] = list(item.claims)
    return row


def requests(
    items: Sequence[AssessableEvidence], *, objective: str, variant: str,
    max_state_chars: int = 6000,
) -> list[ScreenRequest]:
    if variant not in {"compact", "full", "batched", "batched_refs"}:
        raise ValueError("Unknown screening experiment variant")
    if len({item.evidence_id for item in items}) != len(items):
        raise ValueError("Replay evidence IDs must be unique")
    output = []
    batched = variant.startswith("batched")
    size = 2 if batched else 1
    for offset in range(0, len(items), size):
        selected = items[offset:offset + size]
        if variant == "compact":
            state, _, _ = compact_evidence_item_state(
                objective=objective, item=selected[0], max_state_chars=max_state_chars,
            )
        else:
            state = {"objective": objective, "evidence": [full_row(i, objective) for i in selected]}
        questions, bindings = {}, {}
        for index, item in enumerate(selected):
            for criterion, schema in EVIDENCE_SCREEN_QUESTIONS.items():
                key = f"p{index}_{criterion}" if batched else criterion
                question = dict(schema)
                if variant == "batched":
                    # Reuse the existing question text; bind each judgment to its exact target.
                    question["instructions"] = {
                        "task": schema["instructions"], "evidence": state["evidence"][index],
                    }
                elif variant == "batched_refs":
                    question["instructions"] = {
                        "task": schema["instructions"], "evidence_id": item.evidence_id,
                    }
                questions[key] = question
                bindings[key] = (item.evidence_id, criterion)
        output.append(ScreenRequest(state, questions, bindings))
    return output


async def measure(
    client: JevSystemOne, planned: Sequence[ScreenRequest], *, model: str,
    concurrency: int, timeout_seconds: float,
    journal: list[dict] | None = None,
) -> dict:
    if concurrency < 1 or timeout_seconds <= 0:
        raise ValueError("Concurrency and timeout must be positive")
    slots = asyncio.Semaphore(concurrency)
    scores: dict[str, dict[str, float]] = {}
    calls = journal if journal is not None else []

    async def ask(request: ScreenRequest) -> None:
        body = {"state": request.state, "questions": request.questions, "model": model}
        call = {
            "request_sha256": digest(body), "request_chars": len(json.dumps(body)),
            "question_count": len(request.questions), "status": "queued",
        }
        calls.append(call)
        try:
            async with slots:
                call["status"] = "running"
                result = await client.ask(
                    state=request.state, questions=request.questions,
                    model=model, timeout_seconds=timeout_seconds,
                )
            if set(result.answers) != set(request.bindings):
                raise ValueError("Jev response question IDs do not match the request")
            parsed = {key: parse_noul(result.answers, key) for key in request.bindings}
            for key, (evidence_id, criterion) in request.bindings.items():
                scores.setdefault(evidence_id, {})[criterion] = parsed[key]
            call.update(status="completed", resolved_model=result.model,
                latency_ms=result.latency_ms, usage=asdict(result.usage))
        except JevClientError as exc:
            call.update(status="error", error_category=exc.category)
            raise
        except ValueError:
            call.update(status="error", error_category="schema_validation")
            raise
        except asyncio.CancelledError:
            call["status"] = "cancelled"
            raise

    started = perf_counter()
    tasks = [asyncio.create_task(ask(request)) for request in planned]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    models = {call["resolved_model"] for call in calls}
    if len(models) != 1:
        raise ValueError("Resolved Jev model changed during the experiment")
    return {
        "seconds": perf_counter() - started, "requests": len(calls),
        "evidence_count": len(scores), "scores": scores, "calls": calls,
    }
