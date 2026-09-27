"""Process-local single-flight. The key is an evaluation key, not a transport detail.

A later deployment can replace this with a distributed lock. Callers depend on
`do`, not on the dict living in this process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class SingleFlight:
    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    async def do(self, key: str, factory: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
        """Run `factory` once per key. Returns `(result, joined)`.

        Cancelling a waiter does not cancel the shared evaluation. A failed
        call removes the in-flight entry so the next request can retry.
        """
        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._run(key, factory))
                self._inflight[key] = task
                joined = False
            else:
                joined = True
        return await asyncio.shield(task), joined

    async def _run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        try:
            return await factory()
        finally:
            async with self._lock:
                current = self._inflight.get(key)
                if current is asyncio.current_task():
                    self._inflight.pop(key, None)
