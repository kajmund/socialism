"""Discrete simulated clock for OASIS Reddit (no wall-clock timestamps)."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta


class OasisScenarioClock:
    """Used as `sandbox_clock` on OASIS Platform (Reddit).

    `time_transfer` ignores wall time and builds timestamps from
    `simulation_start` + `day_index` + a monotonic sequence within the day.
    """

    def __init__(self, simulation_start: date):
        self.simulation_start = simulation_start
        self._day_index = 0
        self._seq = 0
        self._lock = threading.Lock()
        self.time_step = 0
        self.real_start_time = datetime.now()
        self.k = 1

    def set_day_index(self, day_index: int) -> None:
        """Zero-based offset from simulation_start (typically tick.day - 1)."""
        with self._lock:
            self._day_index = max(0, day_index)
            self._seq = 0

    def time_transfer(
        self,
        now_time: datetime,
        start_time: datetime,
    ) -> datetime:
        del now_time, start_time
        with self._lock:
            self._seq += 1
            seq = self._seq
            d_index = self._day_index
        day = self.simulation_start + timedelta(days=d_index)
        base = datetime.combine(day, datetime.min.time())
        return base + timedelta(milliseconds=seq)

    def get_time_step(self) -> str:
        return str(self.time_step)
