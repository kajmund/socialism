"""Exclusive OS lock for the whole tenant Catalog lifecycle, not just writes."""

from __future__ import annotations

import fcntl
import time
from pathlib import Path


class TenantLock:
    """`flock` on tenant.lock. Released by the OS if the process dies."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: object | None = None

    def acquire(self, *, timeout: float) -> float:
        if self._handle is not None:
            raise RuntimeError(f"tenant lock already held: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        started = time.perf_counter()
        deadline = started + timeout
        try:
            _wait_exclusive(handle, deadline)
        except (TimeoutError, OSError):
            handle.close()
            raise
        self._handle = handle
        return (time.perf_counter() - started) * 1000

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _wait_exclusive(handle: object, deadline: float) -> None:
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.perf_counter() >= deadline:
                raise TimeoutError("tenant lock timed out")
            time.sleep(0.01)
