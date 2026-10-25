"""Lock instrumentation for the owner's Catalog (no locking behavior change)."""

from __future__ import annotations

import statistics
import threading
import time
from typing import Any

SAMPLE_CAP = 5000


def _thread_key() -> str:
    name = threading.current_thread().name
    if "owner-read" in name:
        return "read"
    if "owner-writer" in name:
        return "writer"
    return "main"


class TimedRLock:
    """RLock wrapper that records acquisition wait and hold time."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.wait_seconds: list[float] = []
        self.hold_seconds: list[float] = []
        self.wait_by_thread: dict[str, list[float]] = {}
        self.hold_by_thread: dict[str, list[float]] = {}
        self._metrics_lock = threading.Lock()
        self._entered_at: dict[int, list[float]] = {}

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        started = time.perf_counter()
        if timeout >= 0:
            acquired = self._lock.acquire(blocking, timeout)
        else:
            acquired = self._lock.acquire(blocking)
        if acquired:
            self._record_wait(time.perf_counter() - started)
        return acquired

    def release(self) -> None:
        thread = threading.get_ident()
        stack = self._entered_at.get(thread)
        if stack:
            started = stack.pop()
            self._record_hold(time.perf_counter() - started)
        self._lock.release()

    def __enter__(self) -> TimedRLock:
        self.acquire()
        self._entered_at.setdefault(threading.get_ident(), []).append(time.perf_counter())
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()

    def _record_wait(self, value: float) -> None:
        rounded = round(value, 6)
        with self._metrics_lock:
            self.wait_seconds.append(rounded)
            del self.wait_seconds[:-SAMPLE_CAP]
            name = _thread_key()
            samples = self.wait_by_thread.setdefault(name, [])
            samples.append(rounded)
            del samples[:-SAMPLE_CAP]

    def _record_hold(self, value: float) -> None:
        rounded = round(value, 6)
        with self._metrics_lock:
            self.hold_seconds.append(rounded)
            del self.hold_seconds[:-SAMPLE_CAP]
            name = _thread_key()
            samples = self.hold_by_thread.setdefault(name, [])
            samples.append(rounded)
            del samples[:-SAMPLE_CAP]

    def report(self) -> dict[str, Any]:
        with self._metrics_lock:
            wait = list(self.wait_seconds)
            hold = list(self.hold_seconds)
            wait_by_thread = {key: list(value) for key, value in self.wait_by_thread.items()}
            hold_by_thread = {key: list(value) for key, value in self.hold_by_thread.items()}

        def stats(values: list[float]) -> dict[str, Any]:
            ordered = sorted(values)
            if not ordered:
                return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "n": 0}
            def pct(share: float) -> float:
                return round(ordered[max(0, int(share * len(ordered)) - 1)], 6)
            return {
                "p50": round(statistics.median(ordered), 6),
                "p95": pct(0.95),
                "p99": pct(0.99),
                "max": round(ordered[-1], 6),
                "n": len(ordered),
            }

        return {
            "wait": stats(wait),
            "hold": stats(hold),
            "wait_by_thread": {name: stats(values) for name, values in wait_by_thread.items()},
            "hold_by_thread": {name: stats(values) for name, values in hold_by_thread.items()},
        }


class ReadWriteLock:
    """Writer-exclusive, reader-shared lock for the isolated Catalog experiment.

    A thread holding the writer lock may re-enter writer/read. A reader may
    re-enter read. Acquiring the writer from inside a read callback raises
    instead of deadlocking; callbacks must use the raw ``db`` for writes.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0
        self._writer_thread: int | None = None
        self._writer_depth = 0
        self._read_depth: dict[int, int] = {}
        self._metrics_lock = threading.Lock()
        self._entered_at: dict[str, dict[int, list[float]]] = {"read": {}, "writer": {}}
        self.wait_seconds: list[float] = []
        self.hold_seconds: list[float] = []
        self.wait_by_thread: dict[str, list[float]] = {}
        self.hold_by_thread: dict[str, list[float]] = {}

    def __enter__(self) -> ReadWriteLock:
        self._enter("writer")
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._exit("writer")

    def reader(self) -> Any:
        return _ReadContext(self, "read")

    def _enter(self, kind: str) -> None:
        started = time.perf_counter()
        tid = threading.get_ident()
        with self._condition:
            if kind == "read":
                if self._writer and self._writer_thread == tid:
                    self._read_depth[tid] = self._read_depth.get(tid, 0) + 1
                elif self._read_depth.get(tid, 0):
                    self._read_depth[tid] += 1
                else:
                    while self._writer or self._waiting_writers:
                        self._condition.wait()
                    self._read_depth[tid] = 1
                self._readers += 1
            elif self._writer and self._writer_thread == tid:
                self._writer_depth += 1
            else:
                if self._read_depth.get(tid, 0):
                    raise RuntimeError("cannot acquire writer lock inside a read callback")
                self._waiting_writers += 1
                try:
                    while self._writer or self._readers:
                        self._condition.wait()
                    self._writer = True
                    self._writer_thread = tid
                    self._writer_depth = 1
                finally:
                    self._waiting_writers -= 1
                    self._condition.notify_all()
        self._record(self.wait_by_thread, kind, time.perf_counter() - started)
        self._entered_at[kind].setdefault(tid, []).append(time.perf_counter())

    def _exit(self, kind: str) -> None:
        tid = threading.get_ident()
        entered = self._entered_at[kind].get(tid, [])
        started = entered.pop() if entered else time.perf_counter()
        with self._condition:
            if kind == "read":
                self._read_depth[tid] -= 1
                if self._read_depth[tid] == 0:
                    del self._read_depth[tid]
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()
            elif self._writer_thread == tid:
                self._writer_depth -= 1
                if self._writer_depth == 0:
                    self._writer = False
                    self._writer_thread = None
                    self._condition.notify_all()
        self._record_metric(self.hold_by_thread, kind, time.perf_counter() - started)

    def _record(self, target: dict[str, list[float]], kind: str, value: float) -> None:
        self._record_metric(target, kind, value)

    def _record_metric(self, target: dict[str, list[float]], kind: str, value: float) -> None:
        rounded = round(value, 6)
        with self._metrics_lock:
            samples = target.setdefault(kind, [])
            samples.append(rounded)
            del samples[:-SAMPLE_CAP]

    def report(self) -> dict[str, Any]:
        with self._metrics_lock:
            wait_by_thread = {key: list(value) for key, value in self.wait_by_thread.items()}
            hold_by_thread = {key: list(value) for key, value in self.hold_by_thread.items()}
        return {
            "wait": _stats([value for values in wait_by_thread.values() for value in values]),
            "hold": _stats([value for values in hold_by_thread.values() for value in values]),
            "wait_by_thread": {key: _stats(value) for key, value in wait_by_thread.items()},
            "hold_by_thread": {key: _stats(value) for key, value in hold_by_thread.items()},
        }


class _ReadContext:
    def __init__(self, lock: ReadWriteLock, kind: str) -> None:
        self.lock = lock
        self.kind = kind

    def __enter__(self) -> _ReadContext:
        self.lock._enter(self.kind)
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.lock._exit(self.kind)


def _stats(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "n": 0}

    def pct(share: float) -> float:
        return round(ordered[max(0, int(share * len(ordered)) - 1)], 6)

    return {
        "p50": round(statistics.median(ordered), 6),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": round(ordered[-1], 6),
        "n": len(ordered),
    }


def enable_lock_probe(catalog: Any) -> None:
    """Opt-in lock wait/hold instrumentation; locking behavior is unchanged."""
    if catalog._lock_probe:
        return
    with catalog._lock:
        if not hasattr(catalog._lock, "report"):
            catalog._lock = TimedRLock()
        catalog._lock_probe = True


def enable_read_write_lock(catalog: Any) -> None:
    """Isolated A/B experiment: readers share, writers remain exclusive."""
    if catalog.lock_mode == "read_write":
        return
    with catalog._lock:
        if catalog.lock_mode == "read_write":
            return
        catalog._lock = ReadWriteLock()
        catalog.lock_mode = "read_write"
        catalog._lock_probe = True


def read_guard(catalog: Any) -> Any:
    if catalog.lock_mode == "read_write":
        return catalog._lock.reader()
    return catalog._lock


def lock_report(catalog: Any) -> dict[str, Any]:
    if not catalog._lock_probe:
        return {"enabled": False}
    report = catalog._lock.report()
    return {"enabled": True, **report}
