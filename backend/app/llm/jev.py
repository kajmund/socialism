"""TypeSafe Jev client. Classifies task needs, never named LLM configurations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.llm.runtime_override import LLMCallKind, SelectionRole

SPEED_CLASSES: tuple[SelectionRole, ...] = ("fast", "balanced", "deep")


class JevError(Exception):
    """Jev request failed or returned an unusable decision."""


@dataclass(frozen=True)
class JevNeedDecision:
    speed_class: SelectionRole
    needs_vision: bool
    needs_tools: bool
    needs_structured_output: bool
    needs_long_context: bool
    confidence: float


def _noul_true(value: object) -> bool:
    return float(value) >= 0.5


def parse_need_decision(payload: dict[str, Any]) -> JevNeedDecision:
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevError("Jev response missing answers")
    speed = answers.get("speed_class")
    if not isinstance(speed, dict):
        raise JevError("Jev response missing speed_class")
    choice = str(speed.get("choice") or "").strip()
    if choice not in SPEED_CLASSES:
        raise JevError(f"invalid Jev speed_class: {choice!r}")
    confidence = speed.get("confidence")
    if confidence is None:
        raise JevError("Jev response missing confidence")
    return JevNeedDecision(
        speed_class=choice,  # type: ignore[arg-type]
        needs_vision=_noul_true(_noul_value(answers, "needs_vision")),
        needs_tools=_noul_true(_noul_value(answers, "needs_tools")),
        needs_structured_output=_noul_true(
            _noul_value(answers, "needs_structured_output")
        ),
        needs_long_context=_noul_true(_noul_value(answers, "needs_long_context")),
        confidence=float(confidence),
    )


def _noul_value(answers: dict[str, Any], key: str) -> object:
    row = answers.get(key)
    if not isinstance(row, dict) or "noul" not in row:
        raise JevError(f"Jev response missing {key}")
    return row["noul"]


def need_questions() -> dict[str, Any]:
    return {
        "speed_class": {
            "type": "choice",
            "instructions": (
                "Which execution depth does this prompt call need? "
                "Judge the task, not a vendor or model name."
            ),
            "criteria": {
                "fast": (
                    "Short, cheap, low-reasoning work: routing, classification, "
                    "headings, raise-hand, or small JSON."
                ),
                "balanced": (
                    "Typical generation: comments, summaries, interviews, "
                    "or moderate reasoning."
                ),
                "deep": (
                    "Hard reasoning: planning, legal interpretation, synthesis, "
                    "or long analysis."
                ),
            },
        },
        "needs_vision": {
            "type": "noul",
            "instructions": (
                "Does the task require understanding images or other visual input?"
            ),
            "criteria": {
                "true": "The call includes or requires image understanding.",
                "false": "Text-only task.",
            },
        },
        "needs_tools": {
            "type": "noul",
            "instructions": "Does the task need tool calling?",
            "criteria": {
                "true": "The model must call tools or functions.",
                "false": "No tool use is required.",
            },
        },
        "needs_structured_output": {
            "type": "noul",
            "instructions": "Does the task require structured JSON output?",
            "criteria": {
                "true": "The reply must be valid JSON or a schema-bound object.",
                "false": "Free-form text is enough.",
            },
        },
        "needs_long_context": {
            "type": "noul",
            "instructions": "Does the task need a long input or output window?",
            "criteria": {
                "true": "Large document, long transcript, or very long output.",
                "false": "Normal chat-sized context is enough.",
            },
        },
    }


class JevNeedClassifier:
    """POST /v1/systemone. Returns conceptual needs, never configuration ids."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    async def classify(
        self,
        *,
        prompt_key: str,
        messages: list[dict[str, Any]],
        call_kind: LLMCallKind,
        state: dict[str, Any],
    ) -> JevNeedDecision:
        del prompt_key, messages, call_kind
        api_key = settings.typesafe_api_key.strip()
        if not api_key:
            raise JevError("TYPESAFE_API_KEY is not configured")
        base = settings.typesafe_base_url.rstrip("/")
        body = {
            "model": settings.jev_model,
            "state": state,
            "questions": need_questions(),
        }
        if self._http is not None:
            response = await self._http.post(
                f"{base}/v1/systemone",
                headers=_headers(api_key),
                json=body,
            )
            return _parse_http(response)
        async with httpx.AsyncClient(timeout=settings.jev_timeout_seconds) as client:
            response = await client.post(
                f"{base}/v1/systemone",
                headers=_headers(api_key),
                json=body,
            )
            return _parse_http(response)


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _parse_http(response: httpx.Response) -> JevNeedDecision:
    if response.status_code >= 400:
        raise JevError(
            f"Jev HTTP {response.status_code}: {response.text[:200]}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise JevError("Jev response is not an object")
    return parse_need_decision(payload)
