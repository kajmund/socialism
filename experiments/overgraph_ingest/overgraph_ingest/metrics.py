"""Percentiles, size buckets, and run metadata for baseline reports."""

from __future__ import annotations

import os
import platform
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

SIZE_BUCKETS = (
    ("0-199", 0, 200),
    ("200-999", 200, 1000),
    ("1000-2999", 1000, 3000),
    ("3000+", 3000, None),
)


def percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def summarize_values(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "median": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
        "mean": statistics.fmean(values),
    }


def summarize_repeats(values: Sequence[float]) -> dict[str, float | None]:
    summary = summarize_values(values)
    if len(values) >= 2:
        summary["stdev"] = statistics.stdev(values)
    else:
        summary["stdev"] = None
    return summary


def size_buckets(sizes: Sequence[int]) -> dict[str, int]:
    counts = {label: 0 for label, _lo, _hi in SIZE_BUCKETS}
    for size in sizes:
        for label, low, high in SIZE_BUCKETS:
            if size >= low and (high is None or size < high):
                counts[label] += 1
                break
    return counts


def count_reasons(reasons: Sequence[str | None]) -> dict[str, int]:
    counter: Counter[str] = Counter(reason or "unspecified" for reason in reasons)
    return dict(counter)


def environment_metadata() -> dict[str, object]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "overgraph": _package_version("overgraph"),
        "pymupdf": _package_version("pymupdf"),
        "python_docx": _package_version("python-docx"),
        "experiment": "overgraph-ingest-phase1",
        "extraction_version": "extract-v1",
        "segmentation_version": "structural-v1",
    }


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"
