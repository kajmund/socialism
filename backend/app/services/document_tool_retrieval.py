"""Rank existing workspace tools with Jev before the expert model sees them.

Jev scores semantic relevance. It does not choose or run tools. A Jev failure
returns the catalog the caller already had.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.jev.system import (
    HttpJevSystemOne,
    JevClientError,
    JevSystemOne,
    classify_jev_error,
    parse_noul,
)
from app.observability.events import log_event
from app.schemas.workspace import WorkspaceState
from app.services.expert_reasoning import EVENT_DATASET_EXPERT_CHAT, build_turn_state

RELEVANCE_KEY = "chat.expert.tool_relevance"
RANK_KEY = "chat.expert.tool_relevance_rank"
REQUIRES_DOCUMENT = frozenset({"read_source", "focus_anchor"})
PINNED_LOOKUP_TOOLS = frozenset({"search_knowledge", "get_workspace_context"})
DOCUMENT_LOOKUP_TOOLS = frozenset({"read_source", "show_document"})
MAY_LEAD_TO = {
    "search_knowledge": ("read_source", "show_document", "focus_anchor"),
    "read_source": ("show_document", "focus_anchor"),
    "show_document": ("focus_anchor", "read_source"),
    "focus_anchor": ("read_source",),
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolRetrievalRecord:
    state_filtered: tuple[str, ...]
    scores: dict[str, float]
    exposed: tuple[str, ...]
    ranking: tuple[str, ...]
    require_tool: bool
    fallback: bool
    error_category: str | None
    latency_ms: float
    reroute: bool


def has_document_target(state: WorkspaceState | dict[str, Any] | None) -> bool:
    if state is None:
        return False
    payload = state.model_dump() if isinstance(state, WorkspaceState) else state
    if payload.get("documents"):
        return True
    selection = payload.get("selection")
    if isinstance(selection, dict) and selection.get("source_id"):
        return True
    mentions = payload.get("document_mentions") or []
    return any(isinstance(row, dict) and row.get("source_object_id") for row in mentions)


def state_filtered_specs(
    specs: list[dict], state: WorkspaceState | dict[str, Any] | None
) -> list[dict]:
    if has_document_target(state):
        return list(specs)
    return [spec for spec in specs if _name(spec) not in REQUIRES_DOCUMENT]


def select_exposed(
    scores: dict[str, float],
    *,
    pinned: frozenset[str] = frozenset(),
) -> list[str]:
    if not scores:
        return []
    ranked = sorted(scores, key=lambda name: scores[name], reverse=True)
    best = scores[ranked[0]]
    kept: list[str] = []
    for name in ranked:
        score = scores[name]
        if len(kept) >= settings.document_tool_relevance_top_k:
            break
        if score < settings.document_tool_relevance_floor:
            continue
        if best - score > settings.document_tool_relevance_gap:
            continue
        kept.append(name)
    names = set(kept)
    for name in list(kept):
        for related in MAY_LEAD_TO.get(name, ()):
            score = scores.get(related)
            if score is None or related in names:
                continue
            if score >= settings.document_tool_relevance_complement_floor:
                names.add(related)
    for name in pinned:
        if name in scores:
            names.add(name)
    return sorted(names, key=lambda name: scores[name], reverse=True)


def pinned_lookup_tools(
    state: WorkspaceState | dict[str, Any] | None,
    available: frozenset[str],
) -> frozenset[str]:
    names = PINNED_LOOKUP_TOOLS & available
    if has_document_target(state):
        names |= DOCUMENT_LOOKUP_TOOLS & available
    return names


def requires_tool_call(ranking: tuple[str, ...], scores: dict[str, float]) -> bool:
    if not ranking:
        return False
    return max(scores.get(name, 0.0) for name in ranking) >= settings.document_tool_require_score


async def expose_workspace_tools(
    *,
    prompts: dict[str, str],
    specs: list[dict],
    message: str,
    workspace_state: WorkspaceState | dict[str, Any] | None,
    tool_result: str | None = None,
    jev: JevSystemOne | None = None,
    reroute: bool = False,
) -> tuple[list[dict], ToolRetrievalRecord]:
    started = time.perf_counter()
    filtered = state_filtered_specs(specs, workspace_state)
    names = tuple(_name(spec) for spec in filtered)
    pinned = pinned_lookup_tools(workspace_state, frozenset(names))
    if not filtered:
        record = _record(
            filtered=names, scores={}, ranking=(), fallback=False,
            error_category=None, started=started, reroute=reroute,
        )
        _log(record)
        return [], record
    try:
        scores = await _score(
            prompts,
            filtered,
            message=message,
            tool_result=tool_result,
            jev=jev,
        )
        ranking = tuple(select_exposed(scores, pinned=pinned))
        by_name = {_name(spec): spec for spec in filtered}
        instruction = prompts[RANK_KEY]
        exposed = [_annotate(by_name[name], scores[name], instruction) for name in ranking]
        record = _record(
            filtered=names, scores=scores, ranking=ranking, fallback=False,
            error_category=None, started=started, reroute=reroute,
        )
        _log(record)
        return exposed, record
    except (JevClientError, KeyError, TypeError, ValueError) as exc:
        record = _record(
            filtered=names,
            scores={},
            ranking=tuple(_name(spec) for spec in filtered),
            fallback=True,
            error_category=classify_jev_error(exc),
            started=started,
            reroute=reroute,
        )
        _log(record)
        return list(filtered), record


def log_tool_choice(record: ToolRetrievalRecord, chosen: list[str]) -> None:
    top = record.ranking[0] if record.ranking and not record.fallback else None
    log_event(
        logger,
        "expert_chat.tool_choice",
        dataset=EVENT_DATASET_EXPERT_CHAT,
        outcome="fallback" if record.fallback else "success",
        fields={
            "tool_choice": {
                "ranking": list(record.ranking),
                "chosen": chosen,
                "top": top,
                "chose_top": top is not None and top in chosen,
                "reroute": record.reroute,
                "fallback": record.fallback,
            }
        },
    )


def _score_questions(prompts: dict[str, str], specs: list[dict]) -> dict[str, Any]:
    raw = prompts.get(RELEVANCE_KEY)
    if not raw or RANK_KEY not in prompts:
        raise JevClientError(
            f"missing prompt {RELEVANCE_KEY}",
            category="schema_validation",
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JevClientError(
            f"invalid prompt {RELEVANCE_KEY}",
            category="schema_validation",
        ) from exc
    instructions = parsed.get("instructions")
    criteria = parsed.get("criteria")
    if not isinstance(instructions, str) or not isinstance(criteria, dict):
        raise JevClientError(
            f"invalid prompt {RELEVANCE_KEY}",
            category="schema_validation",
        )
    questions = {}
    for spec in specs:
        name = _name(spec)
        description = str(spec.get("function", {}).get("description") or "")
        questions[name] = {
            "type": "noul",
            "instructions": instructions.replace("{name}", name).replace("{description}", description),
            "criteria": criteria,
        }
    return questions


async def _score(
    prompts: dict[str, str],
    specs: list[dict],
    *,
    message: str,
    tool_result: str | None,
    jev: JevSystemOne | None,
) -> dict[str, float]:
    questions = _score_questions(prompts, specs)
    state = build_turn_state(
        message,
        workspace_state=None,
        tool_names=list(questions),
        tool_result=tool_result,
    )
    result = await (jev or HttpJevSystemOne()).ask(
        state=_clip(state),
        questions=questions,
        model=settings.jev_model,
        timeout_seconds=settings.document_tool_retrieval_timeout_seconds,
    )
    return {name: parse_noul(result.answers, name) for name in questions}


def _clip(state: dict[str, Any]) -> dict[str, Any]:
    budget = settings.document_tool_retrieval_state_chars
    compact = json.dumps(state, ensure_ascii=False, default=str)
    if len(compact) <= budget:
        return state
    clipped = dict(state)
    for key in ("tool_result", "message"):
        value = clipped.get(key)
        if isinstance(value, str) and len(compact) > budget:
            overflow = len(compact) - budget
            clipped[key] = value[: max(0, len(value) - overflow)]
            compact = json.dumps(clipped, ensure_ascii=False, default=str)
    return clipped


def _annotate(spec: dict, score: float, instruction: str) -> dict:
    function = dict(spec["function"])
    function["description"] = f"jev_relevance: {score:.2f}\n{instruction}\n{function['description']}"
    return {**spec, "function": function}


def _name(spec: dict) -> str:
    return str(spec.get("function", {}).get("name") or "")


def _record(
    *,
    filtered: tuple[str, ...],
    scores: dict[str, float],
    ranking: tuple[str, ...],
    fallback: bool,
    error_category: str | None,
    started: float,
    reroute: bool,
) -> ToolRetrievalRecord:
    return ToolRetrievalRecord(
        state_filtered=filtered,
        scores=scores,
        exposed=ranking,
        ranking=ranking,
        require_tool=requires_tool_call(ranking, scores),
        fallback=fallback,
        error_category=error_category,
        latency_ms=(time.perf_counter() - started) * 1000,
        reroute=reroute,
    )


def _log(record: ToolRetrievalRecord) -> None:
    log_event(
        logger,
        "expert_chat.tool_retrieval",
        dataset=EVENT_DATASET_EXPERT_CHAT,
        outcome="fallback" if record.fallback else "success",
        duration_ms=record.latency_ms,
        fields={
            "tool_retrieval": {
                "state_filtered": list(record.state_filtered),
                "scores": record.scores,
                "exposed": list(record.exposed),
                "ranking": list(record.ranking),
                "require_tool": record.require_tool,
                "latency_ms": record.latency_ms,
                "fallback": record.fallback,
                "error_category": record.error_category,
                "reroute": record.reroute,
            }
        },
    )
