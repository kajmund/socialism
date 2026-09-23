"""Allowlisted JSON for local + Logstash documents. No raw secrets or bodies."""

from __future__ import annotations

import math
from typing import Any

MAX_STRING_CHARS = 2000
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "service_role_key",
    }
)
_RESERVED_RECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "taskName",
    }
)


def sanitize_event_value(value: object, *, max_chars: int = MAX_STRING_CHARS) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars]
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.casefold() in _SECRET_KEYS or any(
                secret in key.casefold() for secret in _SECRET_KEYS
            ):
                cleaned[key] = "[redacted]"
                continue
            cleaned[key] = sanitize_event_value(raw_value, max_chars=max_chars)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize_event_value(item, max_chars=max_chars) for item in value]
    return sanitize_event_value(str(value), max_chars=max_chars)


def sanitize_event_payload(payload: dict[str, Any]) -> dict[str, object]:
    cleaned = sanitize_event_value(payload)
    if not isinstance(cleaned, dict):
        return {}
    return {key: value for key, value in cleaned.items() if key not in _RESERVED_RECORD_KEYS}
