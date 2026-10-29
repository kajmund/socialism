"""Semantic and operational quality formulas for arm comparison.

Semantic quality is computed on clean runs only: technical failures are
excluded from numerator and denominator and never count as a correct decision.
Operational quality includes every live repetition and reports failures.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    repetition: int
    expected: str
    draft: str
    technical_failure: bool = False
    failure_reasons: tuple[str, ...] = ()
    coverage_gate_complete: bool = True
    true_positive_conflict: bool = False
    false_contradiction: bool = False
    jev_calls: int = 0
    input_chars: int = 0
    latency_ms: float = 0.0
    jev_latency_ms: float = 0.0
    llm_calls: int = 0
    embedding_calls: int = 0

    @property
    def clean(self) -> bool:
        return not self.technical_failure and self.coverage_gate_complete

    @property
    def correct(self) -> bool:
        return self.draft == self.expected


def semantic_metrics(outcomes: Sequence[CaseOutcome]) -> dict[str, object]:
    rows = [row for row in outcomes if row.clean]
    confusion = Counter(
        _confusion_key(row) for row in rows
    )
    return {
        "population": "clean",
        "clean_runs": len(rows),
        "excluded_runs": len(outcomes) - len(rows),
        "accuracy": _ratio(sum(row.correct for row in rows), len(rows)),
        "false_sufficient": _ratio(
            sum(
                row.draft == "sufficient" and row.expected == "insufficient"
                for row in rows
            ),
            sum(row.expected == "insufficient" for row in rows),
        ),
        "false_insufficient": _ratio(
            sum(
                row.draft == "insufficient" and row.expected == "sufficient"
                for row in rows
            ),
            sum(row.expected == "sufficient" for row in rows),
        ),
        "confusion": dict(confusion),
        "true_positive_conflicts": sum(row.true_positive_conflict for row in rows),
        "false_contradictions": sum(row.false_contradiction for row in rows),
    }


def operational_metrics(outcomes: Sequence[CaseOutcome]) -> dict[str, object]:
    total = len(outcomes)
    failures = [row for row in outcomes if row.technical_failure]
    sufficient_on_failed = [
        row
        for row in outcomes
        if row.technical_failure and row.draft == "sufficient"
    ]
    return {
        "population": "all_live",
        "runs": total,
        "raw_accuracy": _ratio(sum(row.correct for row in outcomes), total),
        "operational_success": _ratio(
            sum(row.correct and row.clean for row in outcomes), total
        ),
        "technical_failure_rate": _ratio(len(failures), total),
        "failure_reasons": dict(_reason_counts(failures)),
        "sufficient_on_failed_call": len(sufficient_on_failed),
        "verdict_stability": _stability(outcomes),
    }


def cost_metrics(outcomes: Sequence[CaseOutcome]) -> dict[str, object]:
    clean = [row for row in outcomes if row.clean]
    detections = sum(row.true_positive_conflict for row in clean)
    correct = sum(row.correct for row in clean)
    calls = sum(row.jev_calls for row in outcomes)
    chars = sum(row.input_chars for row in outcomes)
    return {
        "jev_calls": calls,
        "jev_input_chars": chars,
        "embedding_calls": sum(row.embedding_calls for row in outcomes),
        "llm_calls": sum(row.llm_calls for row in outcomes),
        "latency_ms": round(sum(row.latency_ms for row in outcomes), 3),
        "jev_latency_ms": round(sum(row.jev_latency_ms for row in outcomes), 3),
        "detected_contradictions": detections,
        "cost_per_detected_contradiction": _ratio(calls, detections),
        "cost_per_correct_decision": _ratio(calls, correct),
    }


def _stability(outcomes: Sequence[CaseOutcome]) -> dict[str, object]:
    by_case: dict[str, list[CaseOutcome]] = {}
    for row in outcomes:
        by_case.setdefault(row.case_id, []).append(row)
    unstable = [
        case_id
        for case_id, rows in by_case.items()
        if len({row.draft for row in rows}) > 1
    ]
    explained = [
        case_id
        for case_id in unstable
        if any(row.technical_failure for row in by_case[case_id])
    ]
    return {
        "unstable_cases": unstable,
        "unstable_explained_by_failure": explained,
        "unstable_unexplained": [c for c in unstable if c not in explained],
    }


def _confusion_key(row: CaseOutcome) -> str:
    if row.expected == "sufficient" and row.draft == "sufficient":
        return "true_sufficient"
    if row.expected == "insufficient" and row.draft == "sufficient":
        return "false_sufficient"
    if row.expected == "insufficient" and row.draft == "insufficient":
        return "true_insufficient"
    return "false_insufficient"


def _reason_counts(rows: Sequence[CaseOutcome]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.failure_reasons or ("unspecified",))
    return counts


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None
