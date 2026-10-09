"""Jev assessment and deterministic model-profile routing for expert chat."""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from app.config import settings
from app.jev.system import (
    HttpJevSystemOne,
    JevClientError,
    JevErrorCategory,
    JevSystemOne,
    classify_jev_error,
    parse_noul,
)
from app.llm.runtime_override import SelectionRole
from app.observability.events import log_event
from app.schemas.workspace import WorkspaceState

ASSESSMENT_PROMPT_KEY = "chat.expert.reasoning_assessment"
EXPERT_PROMPT_KEYS = frozenset(
    {
        "chat.mode.interview",
        "chat.expert.tool_ack",
        "chat.expert.tool_result",
        "chat.expert.live_speech_listener",
        "chat.expert.live_speech_progress",
        "chat.expert.live_speech_backchannel",
        "chat.expert.live_speech_opening",
        "chat.expert.worker_task",
    }
)
SCORE_KEYS = (
    "simple_operation",
    "analysis",
    "multi_step",
    "comparison",
    "synthesis",
    "conflicting_information",
    "decomposable",
    "parallelizable",
)
SPAWN_SCORE_KEYS = frozenset({"decomposable", "parallelizable"})
NAVIGATION_TOOLS = frozenset(
    {
        "show_document",
        "focus_anchor",
        "show_evidence",
        "show_artifact",
        "show_knowledge",
        "show_comparison",
        "show_relations",
        "open_ingest_picker",
    }
)
_MENTION = re.compile(r"(?<!\w)@([^\s@,;:!?]+)")
_PROFILE_RANK: dict[SelectionRole, int] = {"fast": 0, "balanced": 1, "deep": 2}
_profile_floor: ContextVar[SelectionRole | None] = ContextVar(
    "expert_reasoning_profile_floor", default=None
)
logger = logging.getLogger(__name__)
EVENT_DATASET_EXPERT_CHAT = "socialism.expert_chat"


@dataclass(frozen=True)
class ReasoningScores:
    simple_operation: float
    analysis: float
    multi_step: float
    comparison: float
    synthesis: float
    conflicting_information: float
    decomposable: float
    parallelizable: float


@dataclass(frozen=True)
class RoutingDecision:
    profile: SelectionRole
    scores: ReasoningScores | None
    reason: str
    latency_ms: float
    fallback: bool = False
    error_category: JevErrorCategory | None = None


@dataclass(frozen=True)
class RoutingEventState:
    initial_profile: SelectionRole
    final_profile: SelectionRole
    escalated: bool
    escalation_reason: str | None
    tool_count: int
    turn_latency_ms: float
    phase: str
    spawn_exposed: bool = False


def current_expert_profile() -> SelectionRole | None:
    return _profile_floor.get()


@contextmanager
def bound_expert_profile(profile: SelectionRole | None) -> Iterator[None]:
    if profile is None:
        yield
        return
    token = _profile_floor.set(profile)
    try:
        yield
    finally:
        _profile_floor.reset(token)


def higher_profile(
    current: SelectionRole, candidate: SelectionRole
) -> SelectionRole:
    return candidate if _PROFILE_RANK[candidate] > _PROFILE_RANK[current] else current


def route_scores(scores: ReasoningScores) -> tuple[SelectionRole, str]:
    complex_analysis = (
        scores.analysis >= settings.expert_reasoning_deep_analysis
        or (
            scores.analysis >= settings.expert_reasoning_deep_analysis_combined
            and scores.multi_step >= settings.expert_reasoning_deep_multi_step
        )
    )
    deep_reason = _deep_reason(scores, complex_analysis=complex_analysis)
    fast = (
        scores.simple_operation >= settings.expert_reasoning_fast_simple
        and scores.analysis <= settings.expert_reasoning_fast_analysis_max
        and scores.multi_step <= settings.expert_reasoning_fast_multi_step_max
        and scores.comparison <= settings.expert_reasoning_fast_other_max
        and scores.synthesis <= settings.expert_reasoning_fast_other_max
        and scores.conflicting_information <= settings.expert_reasoning_fast_other_max
    )
    if deep_reason and scores.simple_operation >= settings.expert_reasoning_fast_simple:
        return "balanced", "ambiguous"
    if deep_reason:
        return "deep", deep_reason
    if fast:
        return "fast", "simple_operation"
    return "balanced", "uncertain"


def spawn_should_expose(
    profile: SelectionRole, scores: ReasoningScores | None
) -> bool:
    if profile != "deep" or scores is None:
        return False
    return (
        scores.decomposable >= settings.expert_reasoning_spawn_decomposable
        and scores.parallelizable >= settings.expert_reasoning_spawn_parallelizable
    )


def _deep_reason(scores: ReasoningScores, *, complex_analysis: bool) -> str | None:
    if scores.conflicting_information >= settings.expert_reasoning_deep_conflict:
        return "conflicting_information"
    if scores.synthesis >= settings.expert_reasoning_deep_synthesis:
        return "synthesis"
    if scores.comparison >= settings.expert_reasoning_deep_comparison:
        return "comparison"
    if complex_analysis:
        return "complex_analysis"
    return None


async def assess_expert_reasoning(
    *,
    prompts: dict[str, str],
    state: dict[str, Any],
    jev: JevSystemOne | None = None,
) -> RoutingDecision:
    started = time.perf_counter()
    try:
        questions = _assessment_questions(prompts)
        result = await (jev or HttpJevSystemOne()).ask(
            state=_clip_state(state),
            questions=questions,
            model=settings.jev_model,
            timeout_seconds=settings.expert_reasoning_timeout_seconds,
        )
        scores = ReasoningScores(
            **{key: _score_value(result.answers, key) for key in SCORE_KEYS}
        )
        profile, reason = route_scores(scores)
        return RoutingDecision(
            profile=profile,
            scores=scores,
            reason=reason,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    except (JevClientError, KeyError, TypeError, ValueError) as exc:
        return RoutingDecision(
            profile="balanced",
            scores=None,
            reason="routing_failure",
            latency_ms=(time.perf_counter() - started) * 1000,
            fallback=True,
            error_category=classify_jev_error(exc),
        )


def _assessment_questions(prompts: dict[str, str]) -> dict[str, Any]:
    raw = prompts.get(ASSESSMENT_PROMPT_KEY)
    if not raw:
        raise JevClientError(
            f"missing prompt {ASSESSMENT_PROMPT_KEY}",
            category="schema_validation",
        )
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise JevClientError(
            f"invalid prompt {ASSESSMENT_PROMPT_KEY}",
            category="schema_validation",
        ) from exc
    keys = set(parsed) if isinstance(parsed, dict) else set()
    if keys != set(SCORE_KEYS) and keys != set(SCORE_KEYS) - SPAWN_SCORE_KEYS:
        raise JevClientError(
            f"invalid questions in {ASSESSMENT_PROMPT_KEY}",
            category="schema_validation",
        )
    return parsed


def _score_value(answers: dict[str, Any], key: str) -> float:
    if key not in answers and key in SPAWN_SCORE_KEYS:
        return 0.0
    return parse_noul(answers, key)


def _clip_state(state: dict[str, Any]) -> dict[str, Any]:
    budget = settings.expert_reasoning_state_char_budget
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


def build_turn_state(
    message: str,
    *,
    workspace_state: WorkspaceState | dict[str, Any] | None,
    tool_names: list[str],
    tool_result: str | None = None,
) -> dict[str, Any]:
    workspace = _workspace_summary(workspace_state)
    state: dict[str, Any] = {
        "message": message,
        "mentions": _MENTION.findall(message),
        "tool_candidates": sorted(set(tool_names)),
        **workspace,
    }
    if tool_result is not None:
        state["tool_result"] = tool_result
    return state


def _workspace_summary(
    state: WorkspaceState | dict[str, Any] | None,
) -> dict[str, Any]:
    if state is None:
        return {"document_count": 0, "documents": [], "selection": None, "explicit_document_ids": []}
    payload = state.model_dump() if isinstance(state, WorkspaceState) else state
    documents = payload.get("documents") or []
    selection = payload.get("selection")
    return {
        "document_count": len(documents),
        "documents": [
            {"source_id": row.get("source_id"), "page": row.get("page")}
            for row in documents
            if isinstance(row, dict)
        ],
        "selection": selection if isinstance(selection, dict) else None,
        "explicit_document_ids": [
            row.get("source_object_id")
            for row in (payload.get("document_mentions") or [])
            if isinstance(row, dict) and row.get("source_object_id")
        ],
    }


def scores_dict(scores: ReasoningScores | None) -> dict[str, float]:
    return {} if scores is None else asdict(scores)


def should_reassess_tools(tool_names: list[str] | tuple[str, ...]) -> bool:
    return any(name not in NAVIGATION_TOOLS for name in tool_names)


def emit_routing_event(
    decision: RoutingDecision,
    state: RoutingEventState,
) -> None:
    log_event(
        logger,
        "expert_chat.reasoning_routed",
        dataset=EVENT_DATASET_EXPERT_CHAT,
        outcome="success",
        duration_ms=decision.latency_ms,
        fields={
            "routing": {
                "phase": state.phase,
                "jev_assessment": scores_dict(decision.scores),
                "initial_profile": state.initial_profile,
                "final_profile": state.final_profile,
                "routing_latency_ms": decision.latency_ms,
                "turn_latency_ms": state.turn_latency_ms,
                "escalated": state.escalated,
                "escalation_reason": state.escalation_reason,
                "tool_count": state.tool_count,
                "fallback": decision.fallback,
                "error_category": decision.error_category,
                "spawn_exposed": state.spawn_exposed,
            }
        },
    )
