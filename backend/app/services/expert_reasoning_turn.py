"""Bind reasoning routing to one expert-chat turn without growing chat orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.llm.runtime_override import SelectionRole
from app.services.expert_async_tools import LibraryToolScope
from app.services.document_tool_retrieval import expose_workspace_tools, log_tool_choice
from app.services.expert_reasoning import (
    RoutingEventState,
    assess_expert_reasoning,
    bound_expert_profile,
    build_turn_state,
    emit_routing_event,
    spawn_should_expose,
)
from app.services.expert_worker_spawn import spawn_workers_spec

logger = logging.getLogger(__name__)


async def route_expert_turn(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    persona_kind: str,
    tools: tuple[list[str], list[dict[str, Any]]],
) -> SelectionRole | None:
    try:
        return await _route_expert_turn(scope, prompts, persona_kind, tools)
    except Exception:
        logger.exception("Expert reasoning route failed")
        return None


async def _route_expert_turn(
    scope: LibraryToolScope,
    prompts: dict[str, str],
    persona_kind: str,
    tools: tuple[list[str], list[dict[str, Any]]],
) -> SelectionRole | None:
    chat_tools, workspace_specs = tools
    if persona_kind == "expert" and workspace_specs and settings.document_tool_retrieval_enabled:
        exposed, retrieval = await expose_workspace_tools(
            prompts=prompts,
            specs=workspace_specs,
            message=scope.user_message,
            workspace_state=scope.workspace_state,
        )
        workspace_specs[:] = exposed
        scope.tool_retrieval = retrieval
    if not settings.expert_reasoning_route_enabled or persona_kind != "expert":
        return None
    started = time.perf_counter()
    workspace_tools = [
        str(spec.get("function", {}).get("name") or "") for spec in workspace_specs
    ]
    decision = await assess_expert_reasoning(
        prompts=prompts,
        state=build_turn_state(
            scope.user_message,
            workspace_state=scope.workspace_state,
            tool_names=[*chat_tools, *workspace_tools],
        ),
    )
    scope.reasoning_profile = decision.profile
    scope.reasoning_decision = decision
    scope.turn_started_at = started
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


async def profiled_chunks(
    stream: AsyncIterator[str], profile: SelectionRole | None
) -> AsyncIterator[str]:
    with bound_expert_profile(profile):
        async for chunk in stream:
            yield chunk


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
