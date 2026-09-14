"""Serialize chat + tool-call messages for OpenAI-compatible providers.

DeepSeek V4 rejects replayed assistant/tool turns that drop `type` on
tool_calls or omit `reasoning_content` after a thinking-mode tool call.
Cerebras gets standard OpenAI-compatible dicts without that extra field.
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


def normalize_messages_for_provider(
    messages: list[dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    if provider == "deepseek":
        return normalize_messages_for_deepseek(messages)
    if provider == "cerebras":
        return normalize_messages_for_openai(messages)
    raise RuntimeError(f"unknown LLM_PROVIDER: {provider}")


def normalize_messages_for_deepseek(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coerce a working transcript into DeepSeek-safe dicts before the HTTP call."""
    return [_normalize_message(item, include_reasoning=True) for item in messages]


def normalize_messages_for_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Standard Chat Completions dicts: no DeepSeek reasoning_content field."""
    return [_normalize_message(item, include_reasoning=False) for item in messages]


def _normalize_message(message: object, *, include_reasoning: bool) -> dict[str, Any]:
    if not isinstance(message, dict):
        payload = assistant_message_dict(message)
        if not include_reasoning:
            payload.pop("reasoning_content", None)
        return payload

    role = message.get("role")
    if role == "assistant":
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": _text_content(message.get("content")),
        }
        if include_reasoning:
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

    content = message.get("content")
    if role == "user" and _is_multimodal_content(content):
        return {"role": role, "content": _normalize_multimodal_content(content)}

    return {
        "role": role,
        "content": _text_content(content),
    }


def _is_multimodal_content(content: object) -> bool:
    if not isinstance(content, list) or not content:
        return False
    return any(
        isinstance(part, dict)
        and part.get("type") in {"image_url", "text", "input_image"}
        for part in content
    )


def _normalize_multimodal_content(content: object) -> list[dict[str, Any]]:
    """Keep text + image_url parts; drop unknown part types."""
    if not isinstance(content, list):
        return [{"type": "text", "text": _text_content(content)}]
    out: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                out.append({"type": "text", "text": text})
            continue
        if part_type == "image_url":
            image = part.get("image_url")
            if isinstance(image, dict) and isinstance(image.get("url"), str):
                out.append({"type": "image_url", "image_url": {"url": image["url"]}})
            elif isinstance(image, str) and image.strip():
                out.append({"type": "image_url", "image_url": {"url": image}})
            continue
    if not out:
        return [{"type": "text", "text": ""}]
    return out


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
