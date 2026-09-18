"""Shared retry seam for structured LLM responses.

One extra model attempt on truncated / invalid JSON or empty output.
Does not repair JSON in code. Provider, timeout, and auth errors propagate.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

logger = logging.getLogger(__name__)

Completer = Callable[..., Awaitable[Any]]
OnRetry = Callable[[], None]

RETRYABLE_CATEGORIES = frozenset({"json_invalid", "length", "empty"})

DEFAULT_STRUCTURED_RETRY_INSTRUCTION = (
    "The previous response was invalid or truncated JSON. "
    "Return one complete JSON object that matches the required schema. "
    "No markdown and no extra text."
)


class StructuredOutputError(RuntimeError):
    """Classified structured-output failure. Not a transport/auth error."""

    def __init__(
        self,
        category: str,
        *,
        finish_reason: str | None = None,
        message: str | None = None,
    ) -> None:
        self.category = category
        self.finish_reason = finish_reason
        super().__init__(
            message
            or f"structured output failed: category={category}"
            + (f" finish_reason={finish_reason}" if finish_reason else "")
        )


def is_json_syntax_validation_error(exc: ValidationError) -> bool:
    return any(error.get("type") == "json_invalid" for error in exc.errors())


def validation_category(exc: ValidationError) -> str:
    types = [error.get("type") for error in exc.errors() if error.get("type")]
    return str(types[0]) if types else "unknown"


def classify_structured_failure(exc: BaseException) -> str:
    if isinstance(exc, StructuredOutputError):
        return exc.category
    if isinstance(exc, ValidationError):
        return validation_category(exc)
    return type(exc).__name__


def _finish_reason_of(exc: BaseException) -> str | None:
    if isinstance(exc, StructuredOutputError):
        return exc.finish_reason
    return None


def is_retryable_structured_failure(exc: BaseException) -> bool:
    if isinstance(exc, StructuredOutputError):
        return exc.category in RETRYABLE_CATEGORIES
    if isinstance(exc, ValidationError):
        return is_json_syntax_validation_error(exc)
    return False


def _log_structured_failure(
    *,
    response_model: type[Any],
    attempt: int,
    exc: BaseException,
    retrying: bool,
) -> None:
    category = classify_structured_failure(exc)
    finish_reason = _finish_reason_of(exc)
    suffix = ", retrying once" if retrying else ""
    logger.info(
        "structured output schema=%s attempt=%s category=%s finish_reason=%s%s",
        getattr(response_model, "__name__", "ResponseModel"),
        attempt,
        category,
        finish_reason,
        suffix,
    )


async def run_structured_with_retry[T](
    completer: Completer,
    messages: list[dict[str, Any]],
    response_model: type[T],
    *,
    retry_instruction: str | None = None,
    on_retry: OnRetry | None = None,
    **completer_kwargs: Any,
) -> T:
    """Call ``completer`` once, then at most one retry on retryable output errors."""
    try:
        return await completer(messages, response_model, **completer_kwargs)
    except Exception as exc:
        if not is_retryable_structured_failure(exc):
            raise
        _log_structured_failure(
            response_model=response_model,
            attempt=1,
            exc=exc,
            retrying=True,
        )
        if on_retry is not None:
            on_retry()
        instruction = (retry_instruction or DEFAULT_STRUCTURED_RETRY_INSTRUCTION).strip()
        retry_messages = [*messages, {"role": "user", "content": instruction}]
        try:
            return await completer(retry_messages, response_model, **completer_kwargs)
        except Exception as retry_exc:
            _log_structured_failure(
                response_model=response_model,
                attempt=2,
                exc=retry_exc,
                retrying=False,
            )
            raise
