"""Voice-only hook for tool progress. Text chat leaves the handler unset."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal


ProgressKind = Literal["started", "partial", "followup"]


@dataclass(frozen=True, slots=True)
class ToolProgress:
    kind: ProgressKind
    tool_name: str
    remaining: int
    summary: str


ProgressHandler = Callable[[ToolProgress], Awaitable[None]]
_handler: ContextVar[ProgressHandler | None] = ContextVar(
    "live_speech_progress", default=None
)


@contextmanager
def bind_tool_progress(handler: ProgressHandler) -> Iterator[None]:
    token = _handler.set(handler)
    try:
        yield
    finally:
        _handler.reset(token)


async def emit_tool_progress(
    kind: ProgressKind,
    tool_name: str,
    *,
    remaining: int,
    summary: str = "",
) -> None:
    handler = _handler.get()
    if handler is None:
        return
    await handler(
        ToolProgress(
            kind=kind,
            tool_name=tool_name,
            remaining=remaining,
            summary=summary[:400],
        )
    )
