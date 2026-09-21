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
from app.llm.runtime_override import (
    bound_llm_retry,
    current_resolution,
    current_retry,
    current_runtime,
)
from app.llm.selection import llm_call_runtime
from app.llm.structured_retry import (
    StructuredOutputError,
    classify_structured_failure,
    is_json_syntax_validation_error,
    run_structured_with_retry,
    validation_category,
)
from app.llm.structured_schema import strict_json_schema
from app.llm.tool_messages import normalize_messages_for_provider
from app.schemas.domain import EditablePersona

ChatMessage = dict[str, Any]
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
_UNSET = object()


@dataclass(frozen=True)
class LLMCallStats:
    provider: str
    model: str
    reasoning_effort: str | None
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: float
    kind: LLMCallKind
    prompt_key: str | None = None
    selection_mode: str | None = None
    selected_configuration_id: int | None = None
    auto_confidence: float | None = None
    reason_code: str | None = None
    retry: bool = False
    failed: bool = False


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
    runtime = current_runtime()
    api_key = runtime.api_key
    if not api_key:
        env_name = (
            "CEREBRAS_API_KEY" if runtime.provider == "cerebras" else "DEEPSEEK_API_KEY"
        )
        raise RuntimeError(
            f"{env_name} is not configured for LLM_PROVIDER={runtime.provider}"
        )
    fingerprint = (
        runtime.provider,
        api_key,
        runtime.base_url,
        settings.llm_timeout_seconds,
    )
    if _client is None or _client_fingerprint != fingerprint:
        _client = AsyncOpenAI(
            api_key=api_key,
            base_url=runtime.base_url,
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
    return chosen or current_runtime().model


def _supports_reasoning_effort(provider: str) -> bool:
    if provider == "cerebras":
        return "reasoning_effort" in _openai_create_params
    # Chat Completions field; Responses API uses reasoning.effort instead.
    return provider == "deepseek"


def _attach_reasoning_effort(kwargs: dict[str, Any], effort: str) -> None:
    if "reasoning_effort" in _openai_create_params:
        kwargs["reasoning_effort"] = effort
        return
    extra = dict(kwargs.get("extra_body") or {})
    extra["reasoning_effort"] = effort
    kwargs["extra_body"] = extra


def _structured_schema_name(response_model: type[Any]) -> str:
    name = getattr(response_model, "__name__", "").strip()
    return name or "ResponseModel"


def _structured_response_format(
    response_model: type[Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    # Cerebras gpt-oss-120b rejects tools + response_format on one request.
    # This path is schema-only; tool calls stay on complete_with_tools.
    if current_runtime().provider == "cerebras":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": _structured_schema_name(response_model),
                "strict": True,
                "schema": schema,
            },
        }
    return {"type": "json_object"}


def _json_object_guide_message(schema: dict[str, Any]) -> ChatMessage:
    return {
        "role": "user",
        "content": (
            "Return ONLY a JSON object matching this JSON Schema "
            f"(no markdown):\n{json.dumps(schema, ensure_ascii=False)}"
        ),
    }


def _cerebras_structured_user_message() -> ChatMessage:
    # Qwen (and some Cerebras chat templates) reject requests with no user turn.
    return {
        "role": "user",
        "content": "Return a JSON object matching the required schema.",
    }


def _messages_have_user_turn(messages: list[Any]) -> bool:
    return any(
        isinstance(row, dict) and row.get("role") == "user" for row in messages
    )


def _chat_create_kwargs(
    *,
    model: str,
    messages: list[Any],
    max_tokens: int | None = None,
    extra: dict[str, Any] | None = None,
    reasoning_effort: Any = _UNSET,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    runtime = current_runtime()
    token_limit = runtime.max_tokens if max_tokens is None else max_tokens
    if token_limit is not None:
        kwargs["max_tokens"] = token_limit
    if runtime.temperature is not None:
        kwargs["temperature"] = runtime.temperature
    if runtime.top_p is not None:
        kwargs["top_p"] = runtime.top_p
    effort = runtime.reasoning_effort if reasoning_effort is _UNSET else reasoning_effort
    if effort is not None and _supports_reasoning_effort(runtime.provider):
        _attach_reasoning_effort(kwargs, str(effort))
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
    failed: bool = False,
) -> None:
    recorder = _usage_recorder.get()
    if recorder is None:
        return
    runtime = current_runtime()
    resolution = current_resolution()
    recorder(
        LLMCallStats(
            provider=runtime.provider,
            model=model,
            reasoning_effort=runtime.reasoning_effort,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=(time.monotonic() - started_at) * 1000,
            kind=kind,
            prompt_key=None if resolution is None else resolution.prompt_key,
            selection_mode=None if resolution is None else resolution.selection_mode,
            selected_configuration_id=(
                None if resolution is None else resolution.selected_configuration_id
            ),
            auto_confidence=None if resolution is None else resolution.auto_confidence,
            reason_code=None if resolution is None else resolution.reason_code,
            retry=current_retry(),
            failed=failed,
        )
    )


async def complete_structured[T](
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    reasoning_effort: str | None = None,
    prompt_key: str | None = None,
) -> T:
    async with llm_call_runtime(prompt_key, messages, "structured"):
        return await _complete_structured(
            messages,
            response_model,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
        )


async def _complete_structured[T](
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    model: str | None,
    max_tokens: int | None,
    timeout: float | None,
    reasoning_effort: str | None,
) -> T:
    if _structured_completer is not None:
        return await _structured_completer(messages, response_model)  # type: ignore[return-value]

    runtime = current_runtime()
    client = get_client()
    schema = response_model.model_json_schema()  # type: ignore[attr-defined]
    guided = list(messages)
    if runtime.provider == "cerebras":
        schema = strict_json_schema(schema)
        if not _messages_have_user_turn(guided):
            guided.append(_cerebras_structured_user_message())
    else:
        guided.append(_json_object_guide_message(schema))
    chosen = _resolved_model(model)
    wait = settings.llm_timeout_seconds if timeout is None else timeout
    started_at = time.monotonic()
    try:
        completion = await asyncio.wait_for(
            client.chat.completions.create(
                **_chat_create_kwargs(
                    model=chosen,
                    messages=guided,
                    max_tokens=(
                        max_tokens if max_tokens is not None else runtime.max_tokens
                    ),
                    extra={
                        "response_format": _structured_response_format(
                            response_model, schema
                        ),
                        # Override the client's global timeout for call sites with a
                        # deliberately different structured-output budget.
                        "timeout": wait,
                    },
                    reasoning_effort=(
                        reasoning_effort if reasoning_effort is not None else _UNSET
                    ),
                )
            ),
            timeout=wait,
        )
    except Exception:
        _record_call(model=chosen, kind="structured", started_at=started_at, failed=True)
        raise
    prompt_tokens, completion_tokens = _usage_tokens(completion)
    _record_call(
        model=chosen,
        kind="structured",
        started_at=started_at,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    choice = completion.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    content = getattr(choice.message, "content", None)
    if finish_reason == "length":
        raise StructuredOutputError("length", finish_reason=finish_reason)
    if not content:
        raise StructuredOutputError(
            "empty",
            finish_reason=finish_reason,
            message="LLM returned empty structured response",
        )
    return response_model.model_validate_json(content)  # type: ignore[attr-defined, no-any-return]


async def complete_structured_retry[T](
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    retry_instruction: str | None = None,
    on_retry: Callable[[], None] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    reasoning_effort: str | None = None,
    prompt_key: str | None = None,
) -> T:
    """Structured completion with one retry on truncated or invalid JSON."""

    async with llm_call_runtime(prompt_key, messages, "structured"):
        attempt = {"n": 0}

        async def _complete(
            retry_messages: list[ChatMessage],
            retry_model: type[T],
        ) -> T:
            attempt["n"] += 1
            with bound_llm_retry(attempt["n"] > 1):
                return await _complete_structured(
                    retry_messages,
                    retry_model,
                    model=model,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    reasoning_effort=reasoning_effort,
                )

        return await run_structured_with_retry(
            _complete,
            messages,
            response_model,
            retry_instruction=retry_instruction,
            on_retry=on_retry,
        )


async def complete_text(
    messages: list[ChatMessage],
    *,
    model: str | None = None,
    prompt_key: str | None = None,
) -> str:
    async with llm_call_runtime(prompt_key, messages, "text"):
        return await _complete_text(messages, model=model)


async def _complete_text(messages: list[ChatMessage], *, model: str | None) -> str:
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


async def stream_text(
    messages: list[ChatMessage],
    *,
    prompt_key: str | None = None,
) -> AsyncIterator[str]:
    """Yield text deltas from the chat completion stream."""
    async with llm_call_runtime(prompt_key, messages, "stream"):
        async for chunk in _stream_text(messages):
            yield chunk


async def _stream_text(messages: list[ChatMessage]) -> AsyncIterator[str]:
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
    chosen = current_runtime().model
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


@dataclass(frozen=True)
class StreamTextMetrics:
    text: str
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: float
    time_to_first_token_ms: float | None
    finish_reason: str | None


async def stream_text_with_metrics(
    messages: list[ChatMessage],
    *,
    prompt_key: str | None = None,
) -> StreamTextMetrics:
    """Stream a completion and return text plus usage / latency metrics."""
    async with llm_call_runtime(prompt_key, messages, "stream"):
        return await _stream_text_with_metrics(messages)


async def _stream_text_with_metrics(messages: list[ChatMessage]) -> StreamTextMetrics:
    if _text_streamer is not None or _text_completer is not None:
        raise RuntimeError(
            "stream_text_with_metrics requires provider usage; "
            "injected text completer/streamer cannot supply token counts"
        )

    client = get_client()
    chosen = current_runtime().model
    started_at = time.monotonic()
    stream = await client.chat.completions.create(
        **_chat_create_kwargs(
            model=chosen,
            messages=messages,
            extra={
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
    )
    parts: list[str] = []
    ttft_ms: float | None = None
    finish_reason: str | None = None
    prompt_tokens = 0
    completion_tokens = 0
    async for event in stream:
        usage = getattr(event, "usage", None)
        if usage is not None:
            prompt_tokens, completion_tokens = _usage_tokens(event)
        choice = event.choices[0] if event.choices else None
        if choice is None:
            continue
        if getattr(choice, "finish_reason", None):
            finish_reason = choice.finish_reason
        delta = choice.delta
        if delta is None:
            continue
        piece = delta.content
        if piece:
            if ttft_ms is None:
                ttft_ms = (time.monotonic() - started_at) * 1000
            parts.append(piece)
    elapsed_ms = (time.monotonic() - started_at) * 1000
    text_out = "".join(parts)
    if prompt_tokens <= 0 and completion_tokens <= 0:
        raise RuntimeError(
            "LLM stream returned no usage tokens "
            "(stream_options.include_usage required)"
        )
    _record_call(
        model=chosen,
        kind="stream",
        started_at=started_at,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return StreamTextMetrics(
        text=text_out,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        elapsed_ms=elapsed_ms,
        time_to_first_token_ms=ttft_ms,
        finish_reason=finish_reason,
    )


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
    *,
    prompt_key: str | None = None,
) -> Any:
    """One chat.completions turn; may return tool_calls. Injectable for tests."""
    async with llm_call_runtime(prompt_key, messages, "tools"):
        return await _complete_with_tools(messages, tools)


async def _complete_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> Any:
    if _tools_completer is not None:
        return await _tools_completer(messages, tools)
    if _text_completer is not None:
        content = await _text_completer(messages)  # type: ignore[arg-type]
        return SimpleNamespace(content=content, tool_calls=None)

    runtime = current_runtime()
    client = get_client()
    chosen = runtime.model
    extra: dict[str, Any] = {}
    if tools:
        extra["tools"] = tools
        extra["tool_choice"] = "auto"
    started_at = time.monotonic()
    completion = await client.chat.completions.create(
        **_chat_create_kwargs(
            model=chosen,
            messages=normalize_messages_for_provider(messages, runtime.provider),
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


async def generate_editable_persona(
    messages: list[ChatMessage],
    *,
    prompt_key: str | None = None,
) -> EditablePersona:
    return await complete_structured(
        messages, EditablePersona, prompt_key=prompt_key
    )


async def invoke_structured_completer[T](
    completer: Completer,
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    prompt_key: str,
) -> T:
    if completer is complete_structured or completer is complete_structured_retry:
        return await completer(messages, response_model, prompt_key=prompt_key)
    return await completer(messages, response_model)  # type: ignore[return-value]
