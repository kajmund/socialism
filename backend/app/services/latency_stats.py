"""Percentile aggregation for live speech latency measurement (§7)."""

from __future__ import annotations

import logging
from typing import Any


def percentiles(samples: list[float]) -> tuple[float, float, float]:
    """Return (p50, p95, p99) with linear interpolation; zeros when empty."""
    if not samples:
        return (0.0, 0.0, 0.0)
    ordered = sorted(samples)
    return (
        _quantile(ordered, 0.50),
        _quantile(ordered, 0.95),
        _quantile(ordered, 0.99),
    )


def _quantile(ordered: list[float], q: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    index = q * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


class LatencyStats:
    """Collect named phase timings and summarize their percentiles."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger
        self._samples: dict[str, list[float]] = {}

    def add(self, phase: str, milliseconds: float) -> None:
        if self._logger is not None:
            self._logger.info(
                "live_speech.latency phase=%s latency_ms=%.1f", phase, milliseconds,
            )
        self._samples.setdefault(phase, []).append(milliseconds)

    def summary(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for phase, samples in self._samples.items():
            p50, p95, p99 = percentiles(samples)
            result[phase] = {
                "count": len(samples),
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "p99_ms": round(p99, 1),
            }
        return result
