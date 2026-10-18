"""Transcript traces and reply notices for expert-chat tool episodes.

``expert_reasoning_episode`` keeps the turn loop small by importing these
self-contained helpers back from here. Nothing in this module imports the
episode module, so it cannot create an import cycle with the loop that owns
the turn state.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from app.llm.chat_model import current_chat_model
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.services.expert_async_tools import PlannedCall, ToolWork

_TRACE_LIMIT = 4000
_trace_tasks: set[asyncio.Task[None]] = set()


def trace_events(
    messages: Sequence[dict[str, Any]],
    specs: Sequence[dict[str, Any]],
    text: str,
    calls: Sequence[PlannedCall],
    *,
    model: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    context = _context_text(messages)
    if context:
        events.append(_traced(kind="context", text=context))
    question = _latest_user_text(messages)
    if question:
        events.append(_traced(kind="message", role="user", text=question))
    offered = _offered_tools(specs)
    if offered:
        events.append(_traced(kind="tools", text=offered))
    visible = text.strip()
    if visible:
        reply: dict[str, Any] = {
            "kind": "message", "role": "assistant", "text": visible[:_TRACE_LIMIT]
        }
        if model:
            reply["model"] = model
        events.append(_traced(**reply))
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


def trace_model_reply(
    work: ToolWork,
    messages: Sequence[dict[str, Any]],
    text: str,
    specs: Sequence[dict[str, Any]] = (),
) -> None:
    episode = work.episode
    customer_id = None if episode is None else episode.customer_id
    schedule_model_traces(
        customer_id,
        work.persona_id,
        trace_events(messages, specs, text, (), model=current_chat_model()),
        target_user_id=work.actor_user_id,
        workspace_id=work.workspace_id,
    )


def _traced(**fields: Any) -> dict[str, Any]:
    return {"trace_id": uuid4().hex, **fields}


def _context_text(messages: Sequence[dict[str, Any]]) -> str:
    parts = [
        _text_content(message.get("content"))
        for message in messages
        if message.get("role") == "system"
    ]
    return "\n\n".join(part for part in parts if part)[:_TRACE_LIMIT]


def _latest_user_text(messages: Sequence[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _text_content(message.get("content"))[:_TRACE_LIMIT]
    return ""


def _offered_tools(specs: Sequence[dict[str, Any]]) -> str:
    names: list[str] = []
    for spec in specs:
        function = spec.get("function") if isinstance(spec, dict) else None
        name = function.get("name") if isinstance(function, dict) else ""
        if name:
            names.append(str(name))
    return "\n".join(names)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
        elif isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


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


_PRESENTATION_TOOLS = frozenset({"show_document", "show_document_set"})
_TEXT_REPLY_NOTICE = json.dumps(
    {
        "text_reply_required": True,
        "say": (
            "Svara användaren i vanlig text utifrån verktygsresultaten. "
            "Vid tvetydig begäran: sammanfatta vad som hittades och ställ "
            "en kort följdfråga."
        ),
    },
    ensure_ascii=False,
)


def _empty_reply_notice(
    *,
    text: str,
    last_text: str,
    messages: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    """Ask once for a plain-text answer when tools ran but produced no text."""
    if (text or last_text).strip():
        return None
    if _text_reply_notice_seen(messages):
        return None
    if not any(message.get("role") == "tool" for message in messages):
        return None
    return {"role": "user", "content": _TEXT_REPLY_NOTICE}


def _text_reply_notice_seen(messages: Sequence[dict[str, Any]]) -> bool:
    needle = '"text_reply_required": true'
    return any(
        message.get("role") == "user" and needle in str(message.get("content") or "")
        for message in messages
    )
