"""DeepSeek client (OpenAI-compatible SDK) + injectable completers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.schemas.domain import EditablePersona

ChatMessage = dict[str, str]
Completer = Callable[[list[ChatMessage], type[Any]], Awaitable[Any]]
TextCompleter = Callable[[list[ChatMessage]], Awaitable[str]]
TextStreamer = Callable[[list[ChatMessage]], AsyncIterator[str]]

_client: AsyncOpenAI | None = None
_structured_completer: Completer | None = None
_text_completer: TextCompleter | None = None
_text_streamer: TextStreamer | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        _client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=settings.deepseek_timeout_seconds,
        )
    return _client


def reset_client() -> None:
    global _client
    _client = None


def set_structured_completer(completer: Completer | None) -> None:
    global _structured_completer
    _structured_completer = completer


def set_text_completer(completer: TextCompleter | None) -> None:
    global _text_completer
    _text_completer = completer


def set_text_streamer(streamer: TextStreamer | None) -> None:
    global _text_streamer
    _text_streamer = streamer


async def complete_structured[T](messages: list[ChatMessage], response_model: type[T]) -> T:
    if _structured_completer is not None:
        return await _structured_completer(messages, response_model)  # type: ignore[return-value]

    client = get_client()
    schema = response_model.model_json_schema()  # type: ignore[attr-defined]
    guided = list(messages)
    guided.append(
        {
            "role": "user",
            "content": (
                "Return ONLY a JSON object matching this JSON Schema "
                f"(no markdown):\n{json.dumps(schema, ensure_ascii=False)}"
            ),
        }
    )
    timeout = settings.deepseek_timeout_seconds
    completion = await asyncio.wait_for(
        client.chat.completions.create(
            model=settings.deepseek_model,
            messages=guided,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
        ),
        timeout=timeout,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("DeepSeek returned empty structured response")
    return response_model.model_validate_json(content)  # type: ignore[attr-defined, no-any-return]


async def complete_text(messages: list[ChatMessage], *, model: str | None = None) -> str:
    if _text_completer is not None:
        return await _text_completer(messages)

    client = get_client()
    completion = await client.chat.completions.create(
        model=model or settings.deepseek_model,
        messages=messages,  # type: ignore[arg-type]
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("DeepSeek returned empty text response")
    return content.strip()


async def stream_text(messages: list[ChatMessage]) -> AsyncIterator[str]:
    """Yield text deltas from the chat completion stream."""
    if _text_streamer is not None:
        async for chunk in _text_streamer(messages):
            yield chunk
        return

    # Tests inject set_text_completer without a streamer — emit one chunk.
    if _text_completer is not None:
        text = await _text_completer(messages)
        if text:
            yield text
        return

    client = get_client()
    stream = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,  # type: ignore[arg-type]
        stream=True,
    )
    async for event in stream:
        choice = event.choices[0] if event.choices else None
        if choice is None or choice.delta is None:
            continue
        piece = choice.delta.content
        if piece:
            yield piece


ToolsCompleter = Callable[
    [list[dict[str, Any]], list[dict[str, Any]] | None],
    Awaitable[Any],
]

_tools_completer: ToolsCompleter | None = None


def set_tools_completer(completer: ToolsCompleter | None) -> None:
    global _tools_completer
    _tools_completer = completer


async def complete_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> Any:
    """One chat.completions turn; may return tool_calls. Injectable for tests."""
    if _tools_completer is not None:
        return await _tools_completer(messages, tools)

    client = get_client()
    kwargs: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    completion = await client.chat.completions.create(**kwargs)
    return completion.choices[0].message


async def generate_editable_persona(messages: list[ChatMessage]) -> EditablePersona:
    return await complete_structured(messages, EditablePersona)
