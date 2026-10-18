"""Aggregate paired benchmark results without changing the output schema."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from scripts.document_presentation_benchmark.types import CaseResult


def summarize_results(rows: Sequence[CaseResult]) -> dict:
    by_arm: dict[str, dict] = {}
    for arm in ("baseline", "treatment"):
        selected = [row for row in rows if row.arm == arm]
        latencies = sorted(row.latency_ms for row in selected)
        by_arm[arm] = {
            "cases": len(selected),
            "latency_ms": {
                "median": round(statistics.median(latencies), 3),
                "p95": round(_percentile(latencies, 0.95), 3),
            },
            "external_calls": {
                "llm": sum(row.calls.llm for row in selected),
                "jev": sum(row.calls.jev for row in selected),
                "embedding": sum(row.calls.embedding for row in selected),
            },
            "document_selection_correct": sum(
                row.document_selection_correct for row in selected
            ),
            "presentation_decision_correct": sum(
                row.presentation_decision_correct for row in selected
            ),
            "intent_pairs_with_equal_selection": _equal_intent_pairs(selected),
        }
    baseline = by_arm["baseline"]
    treatment = by_arm["treatment"]
    paired_equal = _same_case_selections_equal(rows)
    paired_total = len({row.case_id for row in rows})
    return {
        **by_arm,
        "comparison": {
            "median_latency_reduction_ms": round(
                baseline["latency_ms"]["median"] - treatment["latency_ms"]["median"],
                3,
            ),
            "p95_latency_reduction_ms": round(
                baseline["latency_ms"]["p95"] - treatment["latency_ms"]["p95"],
                3,
            ),
            "llm_calls_saved": (
                baseline["external_calls"]["llm"] - treatment["external_calls"]["llm"]
            ),
            "jev_calls_saved": (
                baseline["external_calls"]["jev"] - treatment["external_calls"]["jev"]
            ),
            "paired_selection_equality": {
                "equal": paired_equal,
                "total": paired_total,
                "all_equal": paired_equal == paired_total,
            },
        },
    }


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    rank = (len(values) - 1) * fraction
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _equal_intent_pairs(rows: Sequence[CaseResult]) -> int:
    pairs: dict[str, list[CaseResult]] = {}
    for row in rows:
        pairs.setdefault(row.case_id.split("-", 1)[0], []).append(row)
    return sum(
        len(pair) == 2 and pair[0].source_ids == pair[1].source_ids
        for pair in pairs.values()
    )


def _same_case_selections_equal(rows: Sequence[CaseResult]) -> int:
    cases: dict[str, list[CaseResult]] = {}
    for row in rows:
        cases.setdefault(row.case_id, []).append(row)
    return sum(
        len(pair) == 2 and pair[0].source_ids == pair[1].source_ids
        for pair in cases.values()
    )
