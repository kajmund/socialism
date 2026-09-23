"""Emit one structured event that local logs and Logstash share."""

from __future__ import annotations

import logging
from typing import Any

from app.observability.context import context_fields
from app.observability.sanitize import sanitize_event_payload

EVENT_PAYLOAD_ATTR = "event_payload"
EVENT_DATASET_RESEARCH = "socialism.research"

_RESERVED_ROOT = frozenset({"@timestamp", "message", "log", "process"})


def log_event(
    logger: logging.Logger,
    event_name: str,
    *,
    dataset: str,
    outcome: str = "unknown",
    duration_ms: float | None = None,
    fields: dict[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    """Attach an allowlisted payload. The message is the event name only."""
    event: dict[str, object] = {
        "name": event_name,
        "dataset": dataset,
        "outcome": outcome,
    }
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    payload: dict[str, object] = {"event": event}
    payload.update(context_fields())
    if fields:
        sanitized = sanitize_event_payload(fields)
        for key, value in sanitized.items():
            if key in _RESERVED_ROOT:
                continue
            if key == "event" and isinstance(value, dict):
                merged = dict(payload.get("event") or {})
                merged.update(value)
                payload["event"] = merged
                continue
            if key == "research" and isinstance(value, dict):
                current = payload.get("research")
                if isinstance(current, dict):
                    payload["research"] = {**current, **value}
                    continue
            payload[key] = value
    logger.log(level, event_name, extra={EVENT_PAYLOAD_ATTR: payload})
