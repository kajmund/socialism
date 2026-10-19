"""Context-bound amendment channel for a live-voice turn (Fas 2)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_queue: ContextVar[asyncio.Queue[str] | None] = ContextVar(
    "turn_amendment_queue", default=None
)


@contextmanager
def amendment_channel(queue: asyncio.Queue[str]) -> Iterator[None]:
    token = _queue.set(queue)
    try:
        yield
    finally:
        _queue.reset(token)


@contextmanager
def bound_amendment_channel(runtime) -> Iterator[None]:
    queue: asyncio.Queue[str] = asyncio.Queue()
    runtime._amendment_queue = queue
    with amendment_channel(queue):
        yield


def current_amendment_queue() -> asyncio.Queue[str] | None:
    return _queue.get()


async def drain_amendments(queue: asyncio.Queue[str]) -> list[str]:
    amendments: list[str] = []
    while not queue.empty():
        try:
            amendments.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return amendments
