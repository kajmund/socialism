"""Capture CAMEL external tool usage (search, SymPy) during OASIS runs.

Uses contextvars so parallel A/B variants do not share a single process-global
trace buffer.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

# OASIS social ActionType tool names — external CAMEL tools use other names.
_SOCIAL_TOOL_NAMES = frozenset(
    name.lower()
    for name in (
        "LIKE_POST",
        "DISLIKE_POST",
        "UNLIKE_POST",
        "UNDO_DISLIKE_POST",
        "CREATE_POST",
        "CREATE_COMMENT",
        "LIKE_COMMENT",
        "DISLIKE_COMMENT",
        "UNLIKE_COMMENT",
        "UNDO_DISLIKE_COMMENT",
        "REPOST",
        "QUOTE_POST",
        "FOLLOW",
        "UNFOLLOW",
        "MUTE",
        "UNMUTE",
        "SEARCH_USER",
        "SEARCH_POSTS",
        "REPORT_POST",
        "TREND",
        "DO_NOTHING",
        "REFRESH",
        "INTERVIEW",
    )
)

_TRACE: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "oasis_tool_trace", default=None
)
_TICK_INDEX: ContextVar[int] = ContextVar("oasis_tool_tick", default=0)
_SEQUENCE: ContextVar[int] = ContextVar("oasis_tool_seq", default=0)
_PATCHED = False


def clear_oasis_tool_trace() -> None:
    _TRACE.set([])
    _TICK_INDEX.set(0)
    _SEQUENCE.set(0)


def set_oasis_tool_trace_tick(tick_index: int) -> None:
    _TICK_INDEX.set(max(0, tick_index))
    _SEQUENCE.set(0)


def drain_oasis_tool_trace() -> list[dict[str, Any]]:
    return list(_TRACE.get() or [])


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
    return tool_name.strip().lower() not in _SOCIAL_TOOL_NAMES


def apply_oasis_tool_trace_patch() -> None:
    """Wrap ChatAgent._record_tool_calling to log non-social toolkit usage."""
    global _PATCHED
    if _PATCHED:
        return

    from camel.agents.chat_agent import ChatAgent

    orig_record = ChatAgent._record_tool_calling

    def record_tool_calling(
        self,
        func_name: str,
        args: dict[str, Any],
        result: Any,
        tool_call_id: str,
        mask_output: bool = False,
    ):
        record = orig_record(
            self,
            func_name,
            args,
            result,
            tool_call_id,
            mask_output=mask_output,
        )
        if not is_external_tool(func_name):
            return record

        trace = _TRACE.get()
        if trace is None:
            return record

        seq = _SEQUENCE.get() + 1
        _SEQUENCE.set(seq)
        agent_index = _agent_index(self)
        trace.append(
            {
                "user_id": agent_index if agent_index is not None else -1,
                "tick_index": _TICK_INDEX.get(),
                "sequence": seq,
                "tool_name": func_name,
                "args": _safe_args(args),
                "result_preview": _preview(result),
            }
        )
        return record

    ChatAgent._record_tool_calling = record_tool_calling
    _PATCHED = True
