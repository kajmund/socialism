"""Cancellation signal for the expert turn that owns in-flight tool work."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_cancel: ContextVar[asyncio.Event | None] = ContextVar("expert_turn_cancel", default=None)


def current_turn_cancel() -> asyncio.Event | None:
    return _cancel.get()


def turn_is_cancelled() -> bool:
    event = _cancel.get()
    return event is not None and event.is_set()


@contextmanager
def bind_turn_cancel(event: asyncio.Event) -> Iterator[None]:
    token = _cancel.set(event)
    try:
        yield
    finally:
        _cancel.reset(token)
