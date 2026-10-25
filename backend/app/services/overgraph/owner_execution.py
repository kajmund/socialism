"""Bounded read executor and event-loop lag instrumentation for the owner."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.services.overgraph.owner_client import (
    METRIC_SAMPLES, OwnerMetrics, OwnerUnavailable, _record_sample,
)
from app.services.overgraph.owner_reads import handle_read


class ReadExecutor:
    """Run owner reads on a bounded thread pool, with a close/read barrier."""

    def __init__(self, catalog: Any, metrics: OwnerMetrics, workers: int) -> None:
        self.catalog = catalog
        self.metrics = metrics
        self.executor = (
            ThreadPoolExecutor(max_workers=workers, thread_name_prefix="overgraph-owner-read")
            if workers > 0 else None
        )
        self._inflight = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._idle = asyncio.Event()
        self._idle.set()

    async def read(self, payload: dict[str, Any], catalog_id: str) -> dict[str, Any] | None:
        if self._closed:
            raise OwnerUnavailable("owner is closing")
        if self.executor is None:
            started = time.perf_counter()
            result = handle_read(payload, self.catalog, catalog_id)
            _record_sample(self.metrics.read_seconds, started)
            return result
        self._inflight += 1
        self._idle.clear()
        self._loop = asyncio.get_running_loop()
        return await self._loop.run_in_executor(
            self.executor, self._execute, payload, catalog_id,
        )

    def _execute(self, payload: dict[str, Any], catalog_id: str) -> dict[str, Any] | None:
        started = time.perf_counter()
        try:
            return handle_read(payload, self.catalog, catalog_id)
        finally:
            _record_sample(self.metrics.read_seconds, started)
            self._inflight -= 1
            if self._inflight == 0 and self._loop is not None:
                self._loop.call_soon_threadsafe(self._idle.set)

    async def close(self) -> None:
        self._closed = True
        await self._idle.wait()
        if self.executor is not None:
            self.executor.shutdown(wait=True)
            self.executor = None


class LagMonitor:
    def __init__(self, metrics: OwnerMetrics) -> None:
        self.metrics = metrics
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        interval = 0.005
        next_at = time.perf_counter() + interval
        while True:
            await asyncio.sleep(interval)
            now = time.perf_counter()
            self.metrics.event_loop_lag_seconds.append(round(max(0.0, now - next_at), 6))
            del self.metrics.event_loop_lag_seconds[:-METRIC_SAMPLES]
            next_at = now + interval

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
