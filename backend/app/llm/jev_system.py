"""Generic TypeSafe System One client. Control decisions, not chat completions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from app.config import settings
from app.llm.jev import JevError

JevErrorCategory = Literal[
    "timeout",
    "auth",
    "rate_limit",
    "invalid_response",
    "schema_validation",
    "transport",
    "unknown",
]


class JevClientError(JevError):
    """Typed Jev failure. Research treats this as an expected LLM fallback."""

    def __init__(self, message: str, *, category: JevErrorCategory) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class JevUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class JevSystemOneResult:
    answers: dict[str, Any]
    model: str
    latency_ms: float
    input_chars: int
    usage: JevUsage
    raw: dict[str, Any]


class JevSystemOne(Protocol):
    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult: ...


def classify_jev_error(exc: BaseException) -> JevErrorCategory:
    if isinstance(exc, JevClientError):
        return exc.category
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return "transport"
    return "unknown"


def parse_noul(answers: dict[str, Any], key: str) -> float:
    row = answers.get(key)
    if not isinstance(row, dict) or "noul" not in row:
        raise JevClientError(
            f"Jev response missing noul for {key}",
            category="schema_validation",
        )
    try:
        value = float(row["noul"])
    except (TypeError, ValueError) as exc:
        raise JevClientError(
            f"Jev noul for {key} is not numeric",
            category="schema_validation",
        ) from exc
    if value < 0.0 or value > 1.0:
        raise JevClientError(
            f"Jev noul for {key} is out of range",
            category="schema_validation",
        )
    return value


def noul_confidence(probability: float) -> float:
    return max(probability, 1.0 - probability)


def parse_usage(payload: dict[str, Any]) -> JevUsage:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return JevUsage()
    prompt = _optional_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _optional_int(
        usage.get("completion_tokens") or usage.get("output_tokens")
    )
    total = _optional_int(usage.get("total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return JevUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _category_for_status(status_code: int) -> JevErrorCategory:
    if status_code in {401, 403}:
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if status_code >= 500:
        return "transport"
    return "unknown"


class HttpJevSystemOne:
    """POST /v1/systemone. One request answers every supplied question."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult:
        api_key = settings.typesafe_api_key.strip()
        if not api_key:
            raise JevClientError(
                "TYPESAFE_API_KEY is not configured",
                category="auth",
            )
        body = {"model": model, "state": state, "questions": questions}
        input_chars = _state_chars(state)
        started = time.perf_counter()
        try:
            response = await self._post(body, api_key, timeout_seconds)
        except httpx.TimeoutException as exc:
            raise JevClientError("Jev request timed out", category="timeout") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise JevClientError(
                "Jev transport failed", category="transport"
            ) from exc
        except JevClientError:
            raise
        except Exception as exc:
            raise JevClientError(str(exc), category="unknown") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        payload = _parse_payload(response)
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise JevClientError(
                "Jev response missing answers",
                category="invalid_response",
            )
        resolved_model = str(payload.get("model") or model)
        return JevSystemOneResult(
            answers=answers,
            model=resolved_model,
            latency_ms=latency_ms,
            input_chars=input_chars,
            usage=parse_usage(payload),
            raw=payload,
        )


    async def _post(
        self,
        body: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> httpx.Response:
        base = settings.typesafe_base_url.rstrip("/")
        url = f"{base}/v1/systemone"
        headers = _headers(api_key)
        if self._http is not None:
            return await self._http.post(url, headers=headers, json=body)
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            return await client.post(url, headers=headers, json=body)


def _parse_payload(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        raise JevClientError(
            f"Jev HTTP {response.status_code}",
            category=_category_for_status(response.status_code),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise JevClientError(
            "Jev response is not JSON",
            category="invalid_response",
        ) from exc
    if not isinstance(payload, dict):
        raise JevClientError(
            "Jev response is not an object",
            category="invalid_response",
        )
    return payload


def _state_chars(state: object) -> int:
    if isinstance(state, str):
        return len(state)
    if isinstance(state, dict):
        return len(_canonical_json(state))
    return len(str(state))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
