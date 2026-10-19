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
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from app.database.models import PersonaMessage
from app.llm import complete_text, complete_with_tools
from app.llm.chat_model import current_chat_model
from app.llm.tool_messages import assistant_message_dict, tool_result_message
from app.llm.vision_content import user_content_with_optional_image
from app.services.dd.company_mcp import visible_assistant_text
from app.services.expert_async_tools import (
    PlannedCall,
    ToolWork,
    _planned_calls,
    active_library_tools,
)
from app.services.expert_reasoning_episode_support import (
    _PRESENTATION_TOOLS,
    _TEXT_REPLY_NOTICE,
    _TRACE_LIMIT,
    _empty_reply_notice,
    _text_reply_notice_seen,
    emit_model_traces as emit_model_traces,
    schedule_model_traces,
    trace_events,
    trace_model_reply as trace_model_reply,
    wait_model_traces as wait_model_traces,
)
from app.services.expert_tool_run import tool_failure_text
from app.services.expert_worker_spawn import withhold_incomplete_spawn
from app.services.passage_mark_claim import latest_assistant_text, missing_passage_mark_notice
from app.services.workspace_chat_tools import CLIENT_TOOL_NAMES

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 4
_DISPATCHED = (
    "Sent to the client view. Do not claim it is visible until a later tool result "
    "or user turn confirms completed."
)
_MISSING = "No result."

RunCall = Callable[[PlannedCall, ToolWork], Awaitable[str]]
PublishCalls = Callable[[list[PlannedCall]], Awaitable[None]]


@dataclass(frozen=True)
class ExpertEpisode:
    messages: tuple[dict[str, Any], ...]
    specs: tuple[dict[str, Any], ...]
    prompt_key: str | None
    reasoning_content: str | None
    customer_id: int | None = None
    tool_choice: str = "auto"


def episode_assistant(payload: dict[str, Any], calls: tuple[PlannedCall, ...]) -> dict[str, Any]:
    if not calls:
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
        trace_events(messages, specs, display_text, calls, model=current_chat_model()),
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


class _RoundOutcome(StrEnum):
    CONTINUE = "continue"
    RETURN = "return"
    BREAK = "break"


async def _handle_call_free_round(
    work: ToolWork,
    messages: list[dict[str, Any]],
    *,
    reply: Any,
    payload: dict[str, Any],
    text: str,
    last_text: str,
    episode: ExpertEpisode,
) -> tuple[_RoundOutcome, str]:
    """Append the right notice for a round with no planned tool calls.

    Returns the loop outcome and the visible text to surface on return.
    """
    notice = withhold_incomplete_spawn(messages)
    if notice is not None:
        messages.append(notice)
        _remember_transcript(work, messages)
        return _RoundOutcome.CONTINUE, ""
    mark_notice = missing_passage_mark_notice(text or last_text, messages, episode.specs)
    if mark_notice is not None:
        messages.append(mark_notice)
        _remember_transcript(work, messages)
        return _RoundOutcome.CONTINUE, ""
    text_notice = _empty_reply_notice(
        text=text,
        last_text=last_text,
        messages=messages,
    )
    if text_notice is not None:
        messages.append(text_notice)
        _remember_transcript(work, messages)
        return _RoundOutcome.CONTINUE, ""
    _trace_reply(work, messages, text or last_text, ())
    visible = text or last_text
    if visible.strip():
        return _RoundOutcome.RETURN, visible
    # Empty visible reply: leave the loop for text-only recovery.
    return _RoundOutcome.BREAK, ""


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
    _remember_transcript(work, messages)
    opening_notice = missing_passage_mark_notice(
        latest_assistant_text(messages), messages, episode.specs,
    )
    if opening_notice is not None:
        messages.append(opening_notice)
        _remember_transcript(work, messages)
    last_text = ""
    last_reasoning: str | None = None
    for _ in range(_MAX_ROUNDS):
        episode = work.episode
        if episode is None:
            break
        reply = await complete_with_tools(
            messages,
            list(episode.specs),
            prompt_key=episode.prompt_key,
            tool_choice=episode.tool_choice,
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
                seen_call_ids=work.seen_call_ids,
            )
        )
        if not calls:
            outcome, visible = await _handle_call_free_round(
                work,
                messages,
                reply=reply,
                payload=payload,
                text=text,
                last_text=last_text,
                episode=episode,
            )
            if outcome is _RoundOutcome.CONTINUE:
                continue
            last_reasoning = (
                _reasoning_text(payload.get("reasoning_content")) or last_reasoning
            )
            if outcome is _RoundOutcome.RETURN:
                return visible, last_reasoning
            break
        _trace_reply(work, messages, text, calls)
        assistant = episode_assistant(payload, calls)
        messages.append(assistant)
        if text:
            last_text = text
        last_reasoning = _reasoning_text(assistant.get("reasoning_content")) or last_reasoning
        await _finish_round(messages, calls, work, run_call=run_call, publish=publish)
        _remember_transcript(work, messages)
    recovered = await _recover_empty_text_reply(work, messages, last_text)
    if recovered is not None:
        return recovered, last_reasoning
    return last_text, last_reasoning


def _remember_transcript(work: ToolWork, messages: list[dict[str, Any]]) -> None:
    episode = work.episode
    if episode is None:
        return
    work.episode = ExpertEpisode(
        messages=tuple(dict(message) for message in messages),
        specs=episode.specs,
        prompt_key=episode.prompt_key,
        reasoning_content=episode.reasoning_content,
        customer_id=episode.customer_id,
        tool_choice=episode.tool_choice,
    )


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


async def _recover_empty_text_reply(
    work: ToolWork,
    messages: list[dict[str, Any]],
    last_text: str,
) -> str | None:
    if last_text.strip():
        return None
    if not any(message.get("role") == "tool" for message in messages):
        return None
    episode = work.episode
    prompt_key = "chat.mode.in_character" if episode is None else (
        episode.prompt_key or "chat.mode.in_character"
    )
    if not _text_reply_notice_seen(messages):
        messages.append({"role": "user", "content": _TEXT_REPLY_NOTICE})
        _remember_transcript(work, messages)
    recovered = (await complete_text(messages, prompt_key=prompt_key)).strip()
    if not recovered:
        return None
    _trace_reply(work, messages, recovered, ())
    return recovered


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
    # Client calls are claimed by publish → defer. Server calls skip defer, so
    # mark them here before execution so a later round cannot replay them.
    if client:
        await publish(client)
        _release_required_tool_choice(work, client)
    for call in server:
        work.seen_call_ids.add(call.id)
    texts = await asyncio.gather(
        *(_run_safely(run_call, call, work) for call in server)
    )
    produced = {call.id: text for call, text in zip(server, texts, strict=True)}
    for call in client:
        produced[call.id] = _DISPATCHED
    _trace_rows(work, _append_results(messages, produced))


def _release_required_tool_choice(work: ToolWork, client: list[PlannedCall]) -> None:
    """Stop forcing tools after a presentation call has already been queued.

    Post-find routing may set tool_choice=required so the model must call
    show_document_set. Once that call is published, further required rounds
    only add failure risk before finish_workspace_turn can deliver it.
    """
    episode = work.episode
    if episode is None or episode.tool_choice != "required":
        return
    if not any(call.name in _PRESENTATION_TOOLS for call in client):
        return
    work.episode = replace(episode, tool_choice="auto")


async def _run_safely(run_call: RunCall, call: PlannedCall, work: ToolWork) -> str:
    try:
        return await run_call(call, work)
    except TimeoutError:
        logger.warning("Expert tool %s timed out", call.name)
        work.failed_calls += 1
        return tool_failure_text(call.name, "timeout")
    except Exception:
        logger.exception("Expert tool %s failed", call.name)
        work.failed_calls += 1
        return tool_failure_text(call.name, "error")


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


def _trace_reply(
    work: ToolWork,
    messages: Sequence[dict[str, Any]],
    text: str,
    calls: Sequence[PlannedCall],
) -> None:
    episode = work.episode
    customer_id = None if episode is None else episode.customer_id
    specs = () if episode is None else episode.specs
    schedule_model_traces(
        customer_id,
        work.persona_id,
        trace_events(messages, specs, text, calls, model=current_chat_model()),
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
