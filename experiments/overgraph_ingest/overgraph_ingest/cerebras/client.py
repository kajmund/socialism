"""Synchronous Cerebras chat. CLI credentials only. No env reads."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI


@dataclass(frozen=True)
class CerebrasReply:
    text: str
    ttft_seconds: float | None
    completion_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None = None
    finish_reason: str | None = None


class Completer(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply: ...


class CerebrasClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        max_completion_tokens: int = 8192,
        reasoning_effort: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("--cerebras-api-key is required")
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self.reasoning_effort = reasoning_effort
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)

    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        started = time.perf_counter()
        ttft: float | None = None
        parts: list[str] = []
        usage = None
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_object"},
            "max_completion_tokens": self.max_completion_tokens,
        }
        if self.reasoning_effort is not None:
            kwargs["extra_body"] = {"reasoning_effort": self.reasoning_effort}
        stream = self._client.chat.completions.create(**kwargs)
        finish_reason = None
        for event in stream:
            if getattr(event, "usage", None) is not None:
                usage = event.usage
            if not event.choices:
                continue
            finish_reason = event.choices[0].finish_reason or finish_reason
            text = event.choices[0].delta.content or ""
            if text and ttft is None:
                ttft = time.perf_counter() - started
            parts.append(text)
        payload = "".join(parts)
        reasoning_tokens = _reasoning_tokens(usage)
        if not payload.strip():
            raise EmptyCompletionError(
                finish_reason=finish_reason,
                reasoning_tokens=reasoning_tokens,
                prompt_tokens=None if usage is None else getattr(usage, "prompt_tokens", None),
                completion_tokens=None if usage is None else getattr(usage, "completion_tokens", None),
                completion_seconds=time.perf_counter() - started,
            )
        json.loads(payload)
        prompt_tokens = None if usage is None else getattr(usage, "prompt_tokens", None)
        completion_tokens = None if usage is None else getattr(usage, "completion_tokens", None)
        return CerebrasReply(
            text=payload,
            ttft_seconds=ttft,
            completion_seconds=time.perf_counter() - started,
            prompt_tokens=None if prompt_tokens is None else int(prompt_tokens),
            completion_tokens=None if completion_tokens is None else int(completion_tokens),
            reasoning_tokens=reasoning_tokens,
            finish_reason=finish_reason,
        )


class EmptyCompletionError(ValueError):
    def __init__(
        self,
        *,
        finish_reason: str | None,
        reasoning_tokens: int | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        completion_seconds: float,
    ) -> None:
        self.finish_reason = finish_reason
        self.reasoning_tokens = reasoning_tokens
        self.prompt_tokens = None if prompt_tokens is None else int(prompt_tokens)
        self.completion_tokens = None if completion_tokens is None else int(completion_tokens)
        self.completion_seconds = completion_seconds
        super().__init__(
            "Cerebras returned an empty completion "
            f"(finish_reason={finish_reason}, reasoning_tokens={reasoning_tokens})"
        )


def _reasoning_tokens(usage: object | None) -> int | None:
    if usage is None:
        return None
    details = getattr(usage, "completion_tokens_details", None)
    if details is None:
        return None
    value = getattr(details, "reasoning_tokens", None)
    return None if value is None else int(value)
