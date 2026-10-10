"""Synchronous TypeSafe System One client. No backend imports."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class JevError(Exception):
    def __init__(self, message: str, *, category: str = "unknown") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class JevUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class JevResult:
    answers: dict[str, Any]
    model: str
    latency_ms: float
    usage: JevUsage
    raw: dict[str, Any]


class JevClient(Protocol):
    def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevResult: ...


class HttpJevClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        if not api_key.strip():
            raise JevError("TYPESAFE_API_KEY is required", category="auth")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevResult:
        body = json.dumps(
            {"model": model, "state": state, "questions": questions},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/systemone",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise JevError(f"Jev HTTP {exc.code}", category=_category(exc.code)) from exc
        except TimeoutError as exc:
            raise JevError("Jev request timed out", category="timeout") from exc
        except urllib.error.URLError as exc:
            raise JevError("Jev transport failed", category="transport") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            raise JevError("Jev response missing answers", category="invalid_response")
        return JevResult(
            answers=payload["answers"],
            model=str(payload.get("model") or model),
            latency_ms=latency_ms,
            usage=_usage(payload),
            raw=payload,
        )


def _category(status_code: int) -> str:
    if status_code in {401, 403}:
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if 400 <= status_code < 500:
        return "invalid_request"
    if status_code >= 500:
        return "transport"
    return "unknown"


def _usage(payload: dict[str, Any]) -> JevUsage:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return JevUsage()
    prompt = _optional_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _optional_int(usage.get("completion_tokens") or usage.get("output_tokens"))
    total = _optional_int(usage.get("total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return JevUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
