"""Capture CAMEL external tool usage (search, SymPy) during OASIS runs.

Uses contextvars so parallel A/B variants do not share a single process-global
trace buffer.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from app.services.simulation.action_catalog import is_external_tool as _catalog_is_external

_TRACE: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "oasis_tool_trace", default=None
)
_REASONING_TRACE: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "oasis_reasoning_trace", default=None
)
_TICK_INDEX: ContextVar[int] = ContextVar("oasis_tool_tick", default=0)
_SEQUENCE: ContextVar[int] = ContextVar("oasis_tool_seq", default=0)


def clear_oasis_tool_trace() -> None:
    _TRACE.set([])
    _REASONING_TRACE.set([])
    _TICK_INDEX.set(0)
    _SEQUENCE.set(0)


def set_oasis_tool_trace_tick(tick_index: int) -> None:
    _TICK_INDEX.set(max(0, tick_index))
    _SEQUENCE.set(0)


def drain_oasis_tool_trace() -> list[dict[str, Any]]:
    return list(_TRACE.get() or [])


def drain_oasis_reasoning_trace() -> list[dict[str, Any]]:
    return list(_REASONING_TRACE.get() or [])


def _preview(value: Any, *, limit: int = 2000) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > 200:
            out[key] = f"{value[:199]}…"
        else:
            out[key] = value
    return out


def _agent_index(agent: Any) -> int | None:
    for attr in ("social_agent_id", "agent_id"):
        raw = getattr(agent, attr, None)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def is_external_tool(tool_name: str) -> bool:
    return _catalog_is_external(tool_name)

