"""Serialize chat + tool-call messages for DeepSeek's Chat Completions API.

DeepSeek V4 rejects replayed assistant/tool turns that drop `type` on
tool_calls or omit `reasoning_content` after a thinking-mode tool call.
Always send plain dicts (not SDK models) so `type` is not stripped.
"""

from __future__ import annotations

import json
from typing import Any


def assistant_message_dict(message: object) -> dict[str, Any]:
    """Replay an assistant turn, including tool_calls and reasoning_content."""
    content = _text_content(getattr(message, "content", None))
    payload: dict[str, Any] = {"role": "assistant", "content": content}
    reasoning = _reasoning_content(message)
    if reasoning is not None:
        payload["reasoning_content"] = reasoning
    tool_calls = getattr(message, "tool_calls", None)
    normalized = _normalize_tool_calls(tool_calls)
    if normalized:
        payload["tool_calls"] = normalized
    return payload


def tool_result_message(*, tool_call_id: str, content: object, name: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": _text_content(content),
    }
    if name:
        payload["name"] = name
    return payload


def normalize_messages_for_deepseek(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coerce a working transcript into DeepSeek-safe dicts before the HTTP call."""
    return [_normalize_message(item) for item in messages]


def _normalize_message(message: object) -> dict[str, Any]:
    if not isinstance(message, dict):
        return assistant_message_dict(message)

    role = message.get("role")
    if role == "assistant":
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": _text_content(message.get("content")),
        }
        reasoning = message.get("reasoning_content")
        if reasoning is not None:
            payload["reasoning_content"] = reasoning
        normalized = _normalize_tool_calls(message.get("tool_calls"))
        if normalized:
            payload["tool_calls"] = normalized
        return payload

    if role == "tool":
        return tool_result_message(
            tool_call_id=str(message.get("tool_call_id") or ""),
            content=message.get("content"),
            name=str(message["name"]) if message.get("name") else None,
        )

    return {
        "role": role,
        "content": _text_content(message.get("content")),
    }


def _normalize_tool_calls(tool_calls: object) -> list[dict[str, Any]]:
    if not tool_calls:
        return []
    out: list[dict[str, Any]] = []
    for call in tool_calls:
        item = _normalize_tool_call(call)
        if item is not None:
            out.append(item)
    return out


def _normalize_tool_call(call: object) -> dict[str, Any] | None:
    if isinstance(call, dict):
        call_id = call.get("id")
        fn = call.get("function") or {}
        if isinstance(fn, dict):
            name = fn.get("name")
            arguments = fn.get("arguments")
        else:
            name = getattr(fn, "name", None)
            arguments = getattr(fn, "arguments", None)
        call_type = call.get("type") or "function"
        index = call.get("index")
    else:
        call_id = getattr(call, "id", None)
        fn = getattr(call, "function", None)
        name = getattr(fn, "name", None) if fn is not None else getattr(call, "name", None)
        arguments = (
            getattr(fn, "arguments", None) if fn is not None else getattr(call, "arguments", None)
        )
        call_type = getattr(call, "type", None) or "function"
        index = getattr(call, "index", None)

    if not call_id or not name:
        return None

    item: dict[str, Any] = {
        "id": call_id,
        "type": "function" if call_type in {None, ""} else str(call_type),
        "function": {
            "name": name,
            "arguments": _arguments_string(arguments),
        },
    }
    if isinstance(index, int):
        item["index"] = index
    return item


def _arguments_string(arguments: object) -> str:
    if arguments is None:
        return "{}"
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)


def _text_content(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        if isinstance(text, str):
            return text
    return json.dumps(content, ensure_ascii=False)


def _reasoning_content(message: object) -> object | None:
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning is not None:
        return reasoning
    dump = getattr(message, "model_dump", None)
    if not callable(dump):
        return None
    data = dump()
    if isinstance(data, dict):
        return data.get("reasoning_content")
    return None
