"""Bind reasoning routing to one expert-chat turn without growing chat orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.jev.system import (
    HttpJevSystemOne,
    JevClientError,
    JevSystemOne,
    JevSystemOneResult,
    parse_noul,
)
from app.llm.runtime_override import SelectionRole
from app.observability.events import log_event
from app.services.expert_async_tools import LibraryToolScope
from app.services.document_tool_retrieval import (
    expose_workspace_tools,
    exposure_for_scores,
    log_tool_choice,
    state_filtered_specs,
    tool_relevance_questions,
)
from app.services.expert_reasoning import (
    EVENT_DATASET_EXPERT_CHAT,
    EXPERT_PROMPT_KEYS,
    SCORE_KEYS,
    RoutingDecision,
    RoutingEventState,
    assess_expert_reasoning,
    assessment_questions,
    bound_expert_profile,
    build_turn_state,
    clip_routing_state,
    decision_from_answers,
    decision_from_failure,
    emit_routing_event,
    spawn_should_expose,
)
from app.services.expert_worker_spawn import spawn_workers_spec
from app.services.workspace_intent import (
    decide_workspace_intent,
    filter_specs_for_intent,
)
from app.services.workspace_task_context import workspace_task_context
from app.services.workspace_turn_state import routing_workspace, with_recent_turns

logger = logging.getLogger(__name__)


async def route_expert_turn(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    persona_kind: str,
    tools: tuple[list[str], list[dict[str, Any]]],
    *,
    prompt_key: str | None = None,
) -> SelectionRole | None:
    try:
        return await _route_expert_turn(
            scope, prompts, persona_kind, tools, prompt_key=prompt_key
        )
    except Exception:
        logger.exception("Expert reasoning route failed")
        return None


async def _route_expert_turn(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    persona_kind: str,
    tools: tuple[list[str], list[dict[str, Any]]],
    *,
    prompt_key: str | None = None,
) -> SelectionRole | None:
    chat_tools, workspace_specs = tools
    scored_state = with_recent_turns(scope.workspace_state, scope.history)
    _lock_intent(scope, persona_kind, workspace_specs)
    retrieval_on = _tool_retrieval_enabled(persona_kind, workspace_specs)
    profile_on = _profile_routing_enabled(persona_kind, prompt_key)
    filtered = state_filtered_specs(workspace_specs, scored_state) if retrieval_on else []
    if retrieval_on and profile_on and filtered:
        return await _route_with_shared_ask(
            scope,
            prompts,
            scored_state=scored_state,
            chat_tools=chat_tools,
            workspace_specs=workspace_specs,
        )
    if retrieval_on:
        await _expose_tools(scope, prompts, workspace_specs, scored_state)
    if not profile_on:
        return None
    return await _route_profile_only(
        scope,
        prompts,
        scored_state=scored_state,
        chat_tools=chat_tools,
        workspace_specs=workspace_specs,
    )


def _lock_intent(
    scope: LibraryToolScope,
    persona_kind: str,
    workspace_specs: list[dict[str, Any]],
) -> None:
    if persona_kind != "expert" or not workspace_specs:
        return
    scope.workspace_intent = decide_workspace_intent(
        scope.user_message,
        scope.workspace_state,
    )
    workspace_specs[:] = filter_specs_for_intent(
        workspace_specs, scope.workspace_intent,
    )


def _tool_retrieval_enabled(
    persona_kind: str, workspace_specs: list[dict[str, Any]],
) -> bool:
    return bool(
        persona_kind == "expert"
        and workspace_specs
        and settings.document_tool_retrieval_enabled
    )


def _profile_routing_enabled(persona_kind: str, prompt_key: str | None) -> bool:
    if not settings.expert_reasoning_route_enabled or persona_kind != "expert":
        return False
    return prompt_key is None or prompt_key in EXPERT_PROMPT_KEYS


async def _expose_tools(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    workspace_specs: list[dict[str, Any]],
    scored_state: dict[str, Any] | None,
) -> None:
    _remember_catalog(scope, prompts, workspace_specs)
    exposed, retrieval = await expose_workspace_tools(
        prompts=prompts,
        specs=workspace_specs,
        message=scope.user_message,
        workspace_state=scored_state,
    )
    _apply_exposure(scope, prompts, workspace_specs, exposed, retrieval=retrieval)


async def _route_with_shared_ask(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    *,
    scored_state: dict[str, Any] | None,
    chat_tools: list[str],
    workspace_specs: list[dict[str, Any]],
) -> SelectionRole:
    """Score tools and the reasoning profile in one Jev request.

    The profile sees the candidate tools. The relevance filter is applied
    locally after the answers come back.
    """
    _remember_catalog(scope, prompts, workspace_specs)
    scope.turn_started_at = time.perf_counter()
    try:
        result = await _ask_shared(
            scope, prompts, scored_state=scored_state, chat_tools=chat_tools,
            workspace_specs=workspace_specs,
        )
    except (JevClientError, KeyError, TypeError, ValueError) as exc:
        return _bind_shared_failure(
            scope, prompts, exc,
            workspace_specs=workspace_specs, scored_state=scored_state,
        )
    return _bind_shared_answers(
        scope, prompts, result.answers,
        latency_ms=result.latency_ms,
        workspace_specs=workspace_specs,
        scored_state=scored_state,
    )


async def _ask_shared(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    *,
    scored_state: dict[str, Any] | None,
    chat_tools: list[str],
    workspace_specs: list[dict[str, Any]],
    jev: JevSystemOne | None = None,
) -> JevSystemOneResult:
    filtered = state_filtered_specs(workspace_specs, scored_state)
    tool_questions = tool_relevance_questions(prompts, filtered)
    reason_questions = assessment_questions(prompts)
    overlap = set(tool_questions) & set(SCORE_KEYS)
    if overlap:
        raise JevClientError(
            f"question keys overlap: {sorted(overlap)}",
            category="schema_validation",
        )
    names = list(tool_questions)
    state = build_turn_state(
        scope.user_message,
        workspace_state=routing_workspace(scored_state),
        tool_names=[*chat_tools, *names],
    )
    turns = scored_state.get("recent_turns") if isinstance(scored_state, dict) else None
    if isinstance(turns, list) and turns:
        state["recent_turns"] = turns
    result = await (jev or HttpJevSystemOne()).ask(
        state=clip_routing_state(state, _shared_state_budget()),
        questions={**reason_questions, **tool_questions},
        model=settings.jev_model,
        timeout_seconds=max(
            settings.expert_reasoning_timeout_seconds,
            settings.document_tool_retrieval_timeout_seconds,
        ),
    )
    return result


def _shared_state_budget() -> int:
    return min(
        settings.expert_reasoning_state_char_budget,
        settings.document_tool_retrieval_state_chars,
    )


def _bind_shared_failure(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    exc: BaseException,
    *,
    workspace_specs: list[dict[str, Any]],
    scored_state: dict[str, Any] | None,
) -> SelectionRole:
    latency_ms = _elapsed_ms(scope)
    exposed, retrieval = exposure_for_scores(
        prompts,
        workspace_specs,
        scored_state,
        {},
        latency_ms=latency_ms,
        failure=exc,
    )
    _apply_exposure(scope, prompts, workspace_specs, exposed, retrieval=retrieval)
    return _commit_route(
        scope,
        prompts,
        decision_from_failure(exc, latency_ms=latency_ms),
        workspace_specs=workspace_specs,
    )


def _bind_shared_answers(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    answers: dict[str, Any],
    *,
    latency_ms: float,
    workspace_specs: list[dict[str, Any]],
    scored_state: dict[str, Any] | None,
) -> SelectionRole:
    tool_names = [
        str(spec.get("function", {}).get("name") or "")
        for spec in state_filtered_specs(workspace_specs, scored_state)
    ]
    try:
        scores = {name: parse_noul(answers, name) for name in tool_names}
        tool_failure = None
    except JevClientError as exc:
        scores = {}
        tool_failure = exc
    try:
        decision = decision_from_answers(answers, latency_ms=latency_ms)
    except JevClientError as exc:
        decision = decision_from_failure(exc, latency_ms=latency_ms)
    exposed, retrieval = exposure_for_scores(
        prompts,
        workspace_specs,
        scored_state,
        scores,
        latency_ms=latency_ms,
        failure=tool_failure,
    )
    _apply_exposure(scope, prompts, workspace_specs, exposed, retrieval=retrieval)
    return _commit_route(
        scope, prompts, decision, workspace_specs=workspace_specs,
    )


def _elapsed_ms(scope: LibraryToolScope) -> float:
    started = scope.turn_started_at
    if started is None:
        raise RuntimeError("expert route has no start time")
    return (time.perf_counter() - started) * 1000


async def _route_profile_only(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    *,
    scored_state: dict[str, Any] | None,
    chat_tools: list[str],
    workspace_specs: list[dict[str, Any]],
) -> SelectionRole:
    workspace_tools = [
        str(spec.get("function", {}).get("name") or "") for spec in workspace_specs
    ]
    scope.turn_started_at = time.perf_counter()
    decision = await assess_expert_reasoning(
        prompts=prompts,
        state=build_turn_state(
            scope.user_message,
            workspace_state=scored_state,
            tool_names=[*chat_tools, *workspace_tools],
        ),
    )
    return _commit_route(
        scope, prompts, decision, workspace_specs=workspace_specs,
    )


def _remember_catalog(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    workspace_specs: list[dict[str, Any]],
) -> None:
    scope.workspace_prompts = prompts
    scope.workspace_tool_catalog = list(workspace_specs)


def _apply_exposure(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    workspace_specs: list[dict[str, Any]],
    exposed: list[dict[str, Any]],
    *,
    retrieval: Any,
) -> None:
    kept = filter_specs_for_intent(exposed, scope.workspace_intent)
    workspace_specs[:] = kept
    scope.tool_retrieval = retrieval
    context_names = (
        retrieval.ranking
        if retrieval.fallback
        else tuple(
            name
            for name in retrieval.ranking
            if retrieval.scores[name] >= settings.document_tool_relevance_floor
        )
    )
    scope.workspace_task_context = workspace_task_context(prompts, context_names)


def _commit_route(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    decision: RoutingDecision,
    *,
    workspace_specs: list[dict[str, Any]],
) -> SelectionRole:
    scope.reasoning_profile = decision.profile
    scope.reasoning_decision = decision
    started = scope.turn_started_at
    if started is None:
        raise RuntimeError("expert route has no start time")
    spec = None
    if spawn_should_expose(decision.profile, decision.scores) and scope.workspace_id:
        spec = spawn_workers_spec(prompts)
    scope.spawn_exposed = spec is not None
    if spec is not None:
        workspace_specs.append(spec)
    emit_routing_event(
        decision,
        RoutingEventState(
            initial_profile=decision.profile,
            final_profile=decision.profile,
            escalated=False,
            escalation_reason=None,
            tool_count=0,
            turn_latency_ms=(time.perf_counter() - started) * 1000,
            phase="initial",
            spawn_exposed=scope.spawn_exposed,
        ),
    )
    return decision.profile


async def reroute_workspace_episode(
    scope: LibraryToolScope,
    tool_result: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Re-rank the full workspace catalog after a lookup result."""
    if not scope.workspace_tool_catalog or not scope.workspace_prompts:
        return [], False
    exposed, record = await expose_workspace_tools(
        prompts=scope.workspace_prompts,
        specs=scope.workspace_tool_catalog,
        message=scope.user_message,
        workspace_state=with_recent_turns(scope.workspace_state, scope.history),
        tool_result=tool_result,
        reroute=True,
    )
    exposed = filter_specs_for_intent(exposed, scope.workspace_intent)
    require_tool = record.require_tool and (
        scope.workspace_intent is None or scope.workspace_intent.allows_gallery
    )
    return exposed, require_tool


async def profiled_chunks(
    stream: AsyncIterator[str], profile: SelectionRole | None
) -> AsyncIterator[str]:
    started = time.perf_counter()
    first_ms = None
    try:
        with bound_expert_profile(profile):
            async for chunk in stream:
                if first_ms is None and chunk:
                    first_ms = (time.perf_counter() - started) * 1000
                yield chunk
    finally:
        _log_reply(started, first_ms)


def _log_reply(started: float, first_ms: float | None) -> None:
    total_ms = (time.perf_counter() - started) * 1000
    log_event(
        logger,
        "expert_chat.reply",
        dataset=EVENT_DATASET_EXPERT_CHAT,
        outcome="success",
        duration_ms=total_ms,
        fields={"reply": {"time_to_first_token_ms": first_ms, "total_ms": total_ms}},
    )


def emit_final_routing(scope: LibraryToolScope) -> None:
    try:
        _emit_final_routing(scope)
    except Exception:
        logger.exception("Expert reasoning final route log failed")


def _emit_final_routing(scope: LibraryToolScope) -> None:
    retrieval = scope.tool_retrieval
    if retrieval is not None:
        chosen = [call.name for call in (*scope._calls, *scope.client_calls)]
        log_tool_choice(retrieval, chosen)
    decision = scope.reasoning_decision
    if (
        decision is None
        or scope.turn_started_at is None
        or scope.has_deferred_calls
    ):
        return
    emit_routing_event(
        decision,
        RoutingEventState(
            initial_profile=decision.profile,
            final_profile=decision.profile,
            escalated=False,
            escalation_reason=None,
            tool_count=scope.tool_count,
            turn_latency_ms=(time.perf_counter() - scope.turn_started_at) * 1000,
            phase="final",
            spawn_exposed=scope.spawn_exposed,
        ),
    )
