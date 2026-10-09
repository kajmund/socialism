"""One expert-chat tool episode: same transcript, same tool schemas.

DeepSeek thinking mode requires every earlier ``reasoning_content`` to be
replayed while the request still carries tools. The visible chat row stores
that text; the client serializer does not. Cerebras drops the field in
``normalize_messages_for_provider``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.database.models import PersonaMessage
from app.llm import complete_with_tools
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.llm.tool_messages import assistant_message_dict, tool_result_message
from app.services.dd.company_mcp import visible_assistant_text
from app.llm.vision_content import user_content_with_optional_image
from app.services.expert_async_tools import (
    PlannedCall,
    ToolWork,
    _planned_calls,
    active_library_tools,
)
from app.services.workspace_chat_tools import CLIENT_TOOL_NAMES

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 4
_TRACE_LIMIT = 4000
_DISPATCHED = "Dispatched to the document view."
_MISSING = "No result."
_trace_tasks: set[asyncio.Task[None]] = set()

RunCall = Callable[[PlannedCall, ToolWork], Awaitable[str]]
PublishCalls = Callable[[list[PlannedCall]], Awaitable[None]]


@dataclass(frozen=True)
class ExpertEpisode:
    messages: tuple[dict[str, Any], ...]
    specs: tuple[dict[str, Any], ...]
    prompt_key: str | None
    reasoning_content: str | None
    customer_id: int | None = None


def episode_assistant(payload: dict[str, Any], calls: tuple[PlannedCall, ...]) -> dict[str, Any]:
    if payload.get("tool_calls") or not calls:
        return payload
    assistant = dict(payload)
    assistant["tool_calls"] = [
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False),
            },
        }
        for call in calls
    ]
    return assistant


def remember_expert_episode(
    messages: list[dict[str, Any]],
    payload: dict[str, Any],
    calls: tuple[PlannedCall, ...],
    specs: Sequence[dict[str, Any]],
    *,
    prompt_key: str | None,
    display_text: str = "",
) -> None:
    scope = active_library_tools()
    if scope is None:
        return
    assistant = episode_assistant(dict(payload), calls)
    customer_id = scope.customer_id if isinstance(scope.customer_id, int) else None
    setattr(scope, "episode", ExpertEpisode(
        messages=(*[dict(message) for message in messages], assistant),
        specs=tuple(specs),
        prompt_key=prompt_key,
        reasoning_content=_reasoning_text(assistant.get("reasoning_content")),
        customer_id=customer_id,
    ))
    schedule_model_traces(
        customer_id,
        scope.persona_id,
        trace_events(display_text, calls),
        target_user_id=scope.actor_user_id,
        workspace_id=scope.workspace_id,
    )


def attach_reply_reasoning(row: PersonaMessage) -> None:
    if row.role != "assistant":
        return
    scope = active_library_tools()
    episode = getattr(scope, "episode", None) if scope is not None else None
    reasoning = None if episode is None else episode.reasoning_content
    if isinstance(reasoning, str) and reasoning:
        row.reasoning_content = reasoning


def history_message(
    role: str,
    content: Any,
    image: str | None,
    reasoning: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": role,
        "content": user_content_with_optional_image(content, image),
    }
    if role == "assistant" and isinstance(reasoning, str) and reasoning:
        payload["reasoning_content"] = reasoning
    return payload


def trace_events(text: str, calls: Sequence[PlannedCall]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    visible = text.strip()
    if visible:
        events.append({"kind": "message", "text": visible[:_TRACE_LIMIT]})
    events.extend(
        {
            "kind": "tool_call",
            "name": call.name,
            "call_id": call.id,
            "arguments": call.arguments,
        }
        for call in calls
    )
    return events


def schedule_model_traces(
    customer_id: int | None,
    persona_id: str,
    events: Sequence[dict[str, Any]],
    *,
    target_user_id: str | None,
    workspace_id: str | None,
) -> None:
    if customer_id is None or not events:
        return
    task = asyncio.create_task(
        emit_model_traces(
            customer_id,
            persona_id,
            events,
            target_user_id=target_user_id,
            workspace_id=workspace_id,
        )
    )
    _trace_tasks.add(task)
    task.add_done_callback(_trace_tasks.discard)


async def wait_model_traces() -> None:
    while _trace_tasks:
        await asyncio.gather(*list(_trace_tasks))


async def emit_model_traces(
    customer_id: int,
    persona_id: str,
    events: Sequence[dict[str, Any]],
    *,
    target_user_id: str | None,
    workspace_id: str | None,
) -> None:
    for event in events:
        await library_chat_broadcast.publish(customer_id, persona_id, {
            "type": "model_trace",
            "thread_type": "expert",
            "thread_id": persona_id,
            "target_user_id": target_user_id,
            "workspace_id": workspace_id,
            **event,
        })


async def continue_expert_episode(
    work: ToolWork,
    results: Sequence[str],
    *,
    run_call: RunCall,
    publish: PublishCalls,
) -> tuple[str, str | None]:
    episode = work.episode
    if episode is None:
        logger.error("Expert tool episode missing for %s", work.persona_id)
        return "", None
    messages = [dict(message) for message in episode.messages]
    _trace_rows(work, _append_results(messages, _result_by_id(work.calls, results)))
    last_text = ""
    last_reasoning: str | None = None
    for _ in range(_MAX_ROUNDS):
        reply = await complete_with_tools(
            messages,
            list(episode.specs),
            prompt_key=episode.prompt_key,
        )
        payload = assistant_message_dict(reply)
        text = visible_assistant_text(payload)
        calls = tuple(
            _planned_calls(
                reply,
                text,
                messages,
                offered=frozenset(
                    str(spec["function"]["name"]) for spec in episode.specs
                ),
                consult=False,
                workspace_state=work.workspace_state,
            )
        )
        if not calls:
            _trace_reply(work, text or last_text, ())
            return text or last_text, _reasoning_text(payload.get("reasoning_content")) or last_reasoning
        _trace_reply(work, text, calls)
        assistant = episode_assistant(payload, calls)
        messages.append(assistant)
        if text:
            last_text = text
        last_reasoning = _reasoning_text(assistant.get("reasoning_content")) or last_reasoning
        await _finish_round(messages, calls, work, run_call=run_call, publish=publish)
    return last_text, last_reasoning


def _result_by_id(calls: tuple[PlannedCall, ...], results: Sequence[str]) -> dict[str, str]:
    return {call.id: result for call, result in zip(calls, results, strict=False)}


def _append_results(messages: list[dict[str, Any]], by_id: dict[str, str]) -> list[tuple[str, str, str]]:
    if not messages:
        return []
    rows: list[tuple[str, str, str]] = []
    for tool_call in _tool_calls(messages[-1]):
        name = _call_name(tool_call)
        call_id = str(tool_call.get("id") or "")
        if call_id in by_id:
            content = by_id[call_id]
        elif name in CLIENT_TOOL_NAMES:
            content = _DISPATCHED
        else:
            content = _MISSING
        rows.append((call_id, name, content))
        messages.append(tool_result_message(tool_call_id=call_id, content=content, name=name))
    return rows


async def _finish_round(
    messages: list[dict[str, Any]],
    calls: tuple[PlannedCall, ...],
    work: ToolWork,
    *,
    run_call: RunCall,
    publish: PublishCalls,
) -> None:
    client = [call for call in calls if call.name in CLIENT_TOOL_NAMES]
    server = [call for call in calls if call.name not in CLIENT_TOOL_NAMES]
    if client:
        await publish(client)
    produced: dict[str, str] = {}
    for call in server:
        produced[call.id] = await _run_safely(run_call, call, work)
    for call in client:
        produced[call.id] = _DISPATCHED
    _trace_rows(work, _append_results(messages, produced))


async def _run_safely(run_call: RunCall, call: PlannedCall, work: ToolWork) -> str:
    try:
        return await run_call(call, work)
    except Exception as exc:
        logger.exception("Expert tool %s failed", call.name)
        return str(exc) or call.name


def _tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _call_name(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "")
    return ""


def _trace_reply(work: ToolWork, text: str, calls: Sequence[PlannedCall]) -> None:
    episode = work.episode
    customer_id = None if episode is None else episode.customer_id
    schedule_model_traces(
        customer_id,
        work.persona_id,
        trace_events(text, calls),
        target_user_id=work.actor_user_id,
        workspace_id=work.workspace_id,
    )


def _trace_rows(work: ToolWork, rows: Sequence[tuple[str, str, str]]) -> None:
    episode = work.episode
    customer_id = None if episode is None else episode.customer_id
    schedule_model_traces(
        customer_id,
        work.persona_id,
        [
            {
                "kind": "tool_result",
                "call_id": call_id,
                "name": name,
                "text": text[:_TRACE_LIMIT],
            }
            for call_id, name, text in rows
        ],
        target_user_id=work.actor_user_id,
        workspace_id=work.workspace_id,
    )


def _reasoning_text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
