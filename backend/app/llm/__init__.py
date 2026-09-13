"""OpenAI-compatible chat client + injectable completers."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

from openai import AsyncOpenAI
from openai.resources.chat.completions import AsyncCompletions

from app.config import settings
from app.llm.tool_messages import normalize_messages_for_provider
from app.schemas.domain import EditablePersona

ChatMessage = dict[str, str]
Completer = Callable[[list[ChatMessage], type[Any]], Awaitable[Any]]
TextCompleter = Callable[[list[ChatMessage]], Awaitable[str]]
TextStreamer = Callable[[list[ChatMessage]], AsyncIterator[str]]
LLMCallKind = Literal["structured", "text", "stream", "tools"]

_client: AsyncOpenAI | None = None
_client_fingerprint: tuple[str, str, str, float] | None = None
_structured_completer: Completer | None = None
_text_completer: TextCompleter | None = None
_text_streamer: TextStreamer | None = None
_openai_create_params = inspect.signature(AsyncCompletions.create).parameters


@dataclass(frozen=True)
class LLMCallStats:
    provider: str
    model: str
    reasoning_effort: str | None
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: float
    kind: LLMCallKind


LLMUsageRecorder = Callable[[LLMCallStats], None]

_usage_recorder: ContextVar[LLMUsageRecorder | None] = ContextVar(
    "llm_usage_recorder", default=None
)


def bind_usage_recorder(recorder: LLMUsageRecorder) -> Token[LLMUsageRecorder | None]:
    return _usage_recorder.set(recorder)


def reset_usage_recorder(token: Token[LLMUsageRecorder | None]) -> None:
    _usage_recorder.reset(token)


def get_client() -> AsyncOpenAI:
    global _client, _client_fingerprint
    api_key = settings.selected_llm_api_key
    if not api_key:
        raise RuntimeError(
            f"{settings.chat_llm_key_env_name} is not configured "
            f"for LLM_PROVIDER={settings.llm_provider}"
        )
    fingerprint = (
        settings.llm_provider,
        api_key,
        settings.selected_llm_base_url,
        settings.llm_timeout_seconds,
    )
    if _client is None or _client_fingerprint != fingerprint:
        _client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.selected_llm_base_url,
            timeout=settings.llm_timeout_seconds,
        )
        _client_fingerprint = fingerprint
    return _client


def reset_client() -> None:
    global _client, _client_fingerprint
    _client = None
    _client_fingerprint = None


def set_structured_completer(completer: Completer | None) -> None:
    global _structured_completer
    _structured_completer = completer


def set_text_completer(completer: TextCompleter | None) -> None:
    global _text_completer
    _text_completer = completer


def set_text_streamer(streamer: TextStreamer | None) -> None:
    global _text_streamer
    _text_streamer = streamer


def _resolved_model(model: str | None) -> str:
    chosen = (model or "").strip()
    return chosen or settings.selected_llm_model


def _supports_reasoning_effort(provider: str) -> bool:
    return provider == "cerebras" and "reasoning_effort" in _openai_create_params


def _structured_schema_name(response_model: type[Any]) -> str:
    name = getattr(response_model, "__name__", "").strip()
    return name or "ResponseModel"


def _structured_response_format(
    response_model: type[Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    # Cerebras gpt-oss-120b rejects tools + response_format on one request.
    # This path is schema-only; tool calls stay on complete_with_tools.
    if settings.llm_provider == "cerebras":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": _structured_schema_name(response_model),
                "strict": True,
                "schema": schema,
            },
        }
    return {"type": "json_object"}


def _structured_guide_message(schema: dict[str, Any]) -> ChatMessage:
    if settings.llm_provider == "cerebras":
        # Schema is already in response_format; do not send a second copy.
        return {
            "role": "user",
            "content": (
                "Return ONLY a JSON object matching the required schema "
                "(no markdown)."
            ),
        }
    return {
        "role": "user",
        "content": (
            "Return ONLY a JSON object matching this JSON Schema "
            f"(no markdown):\n{json.dumps(schema, ensure_ascii=False)}"
        ),
    }


def _chat_create_kwargs(
    *,
    model: str,
    messages: list[Any],
    max_tokens: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    effort = settings.selected_reasoning_effort
    if effort is not None and _supports_reasoning_effort(settings.llm_provider):
        kwargs["reasoning_effort"] = effort
    if extra:
        kwargs.update(extra)
    return kwargs


def _usage_tokens(completion: object) -> tuple[int, int]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "prompt_tokens", None)
    if prompt is None:
        prompt = getattr(usage, "input_tokens", 0)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if completion_tokens is None:
        completion_tokens = getattr(usage, "output_tokens", 0)
    return int(prompt or 0), int(completion_tokens or 0)


def _record_call(
    *,
    model: str,
    kind: LLMCallKind,
    started_at: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    recorder = _usage_recorder.get()
    if recorder is None:
        return
    recorder(
        LLMCallStats(
            provider=settings.llm_provider,
            model=model,
            reasoning_effort=settings.selected_reasoning_effort,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=(time.monotonic() - started_at) * 1000,
            kind=kind,
        )
    )


async def complete_structured[T](
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
) -> T:
    if _structured_completer is not None:
        return await _structured_completer(messages, response_model)  # type: ignore[return-value]

    client = get_client()
    schema = response_model.model_json_schema()  # type: ignore[attr-defined]
    guided = list(messages)
    guided.append(_structured_guide_message(schema))
    chosen = _resolved_model(model)
    timeout = settings.llm_timeout_seconds
    started_at = time.monotonic()
    completion = await asyncio.wait_for(
        client.chat.completions.create(
            **_chat_create_kwargs(
                model=chosen,
                messages=guided,
                max_tokens=(
                    max_tokens
                    if max_tokens is not None
                    else settings.llm_max_tokens
                ),
                extra={
                    "response_format": _structured_response_format(
                        response_model, schema
                    )
                },
            )
        ),
        timeout=timeout,
    )
    prompt_tokens, completion_tokens = _usage_tokens(completion)
    _record_call(
        model=chosen,
        kind="structured",
        started_at=started_at,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned empty structured response")
    return response_model.model_validate_json(content)  # type: ignore[attr-defined, no-any-return]


async def complete_text(messages: list[ChatMessage], *, model: str | None = None) -> str:
    if _text_completer is not None:
        return await _text_completer(messages)

    client = get_client()
    chosen = _resolved_model(model)
    started_at = time.monotonic()
    completion = await client.chat.completions.create(
        **_chat_create_kwargs(model=chosen, messages=messages)
    )
    prompt_tokens, completion_tokens = _usage_tokens(completion)
    _record_call(
        model=chosen,
        kind="text",
        started_at=started_at,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned empty text response")
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
    chosen = settings.selected_llm_model
    started_at = time.monotonic()
    stream = await client.chat.completions.create(
        **_chat_create_kwargs(
            model=chosen,
            messages=messages,
            extra={"stream": True},
        )
    )
    async for event in stream:
        choice = event.choices[0] if event.choices else None
        if choice is None or choice.delta is None:
            continue
        piece = choice.delta.content
        if piece:
            yield piece
    _record_call(model=chosen, kind="stream", started_at=started_at)


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
    if _text_completer is not None:
        content = await _text_completer(messages)  # type: ignore[arg-type]
        return SimpleNamespace(content=content, tool_calls=None)

    client = get_client()
    chosen = settings.selected_llm_model
    extra: dict[str, Any] = {}
    if tools:
        extra["tools"] = tools
        extra["tool_choice"] = "auto"
    started_at = time.monotonic()
    completion = await client.chat.completions.create(
        **_chat_create_kwargs(
            model=chosen,
            messages=normalize_messages_for_provider(
                messages, settings.llm_provider
            ),
            extra=extra or None,
        )
    )
    prompt_tokens, completion_tokens = _usage_tokens(completion)
    _record_call(
        model=chosen,
        kind="tools",
        started_at=started_at,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return completion.choices[0].message


async def generate_editable_persona(messages: list[ChatMessage]) -> EditablePersona:
    return await complete_structured(messages, EditablePersona)
