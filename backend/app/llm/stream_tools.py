"""Streaming tool-call completion for the expert tool episode.

Lives outside ``app/llm/__init__.py`` (which is baselined) and mirrors
``complete_with_tools``, but streams text deltas and reassembles the
message-like result so the episode loop stays unchanged elsewhere.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from app.llm import (
    _UNSET,
    _chat_create_kwargs,
    _record_call,
    _text_completer,
    _tools_completer,
    current_runtime,
    get_client,
    llm_call_runtime,
)
from app.llm.tool_choice import reasoning_effort_for_tool_choice
from app.llm.tool_messages import normalize_messages_for_provider


async def stream_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    prompt_key: str | None = None,
    tool_choice: str = "auto",
    message_out: list[Any],
) -> AsyncIterator[str]:
    """Yield text deltas; append the message-like result to ``message_out``."""
    async with llm_call_runtime(prompt_key, messages, "tools"):
        if _tools_completer is not None:
            reply = await _tools_completer(messages, tools)
            content = getattr(reply, "content", None) or ""
            message_out.append(reply)
            if content:
                yield content
            return
        if _text_completer is not None:
            content = await _text_completer(messages)  # type: ignore[arg-type]
            message_out.append(
                SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
            )
            if content:
                yield content
            return
        runtime = current_runtime()
        extra: dict[str, Any] = {"stream": True}
        if tools:
            extra["tools"] = tools
            extra["tool_choice"] = tool_choice
        started_at = time.monotonic()
        stream = await get_client().chat.completions.create(
            **_chat_create_kwargs(
                model=runtime.model,
                messages=normalize_messages_for_provider(messages, runtime.provider),
                extra=extra,
                reasoning_effort=reasoning_effort_for_tool_choice(tool_choice, runtime)
                or _UNSET,
            )
        )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        async for event in stream:
            choice = event.choices[0] if event.choices else None
            if choice is None or choice.delta is None:
                continue
            delta = choice.delta
            piece = getattr(delta, "content", None)
            if piece:
                content_parts.append(piece)
                yield piece
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_parts.append(reasoning)
            _accumulate_tool_calls(tool_calls, delta)
        _record_call(model=runtime.model, kind="tools", started_at=started_at)
        message_out.append(
            SimpleNamespace(
                content="".join(content_parts),
                reasoning_content="".join(reasoning_parts) or None,
                tool_calls=[
                    SimpleNamespace(
                        id=entry["id"],
                        type="function",
                        function=SimpleNamespace(
                            name=entry["name"], arguments=entry["arguments"],
                        ),
                    )
                    for entry in tool_calls.values()
                ]
                or None,
            )
        )


def _accumulate_tool_calls(
    tool_calls: dict[int, dict[str, str]],
    delta: Any,
) -> None:
    for call in getattr(delta, "tool_calls", None) or []:
        entry = tool_calls.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
        if call.id:
            entry["id"] = call.id
        function = getattr(call, "function", None)
        if function is not None:
            if function.name:
                entry["name"] = function.name
            if function.arguments:
                entry["arguments"] += function.arguments
