"""Replay Coverage v3 timelines at workspace stop budgets. No new Jev or controller."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V3 = ROOT / "data" / "coverage-v3.json"
STOP_BUDGETS = (50, 100, 150, 200, 300)
INVESTIGATION_COMPLETE = "COMPLETE"
INVESTIGATION_PARTIAL = "PARTIAL"
INVESTIGATION_FAILED = "FAILED"
UNRESOLVED_KINDS = (
    "insufficiently_examined",
    "unclear_or_conflicting",
    "composite_incomplete",
)


def replay_gold(gold_row: dict[str, object]) -> dict[str, object]:
    budgets = list(gold_row.get("budgets") or [])
    last = budgets[-1] if budgets else {}
    timeline = list(last.get("timeline") or [])
    expected = int(last.get("documents_expected") or 0)
    final_classified = int(last.get("classified") or 0)
    proof_kind = str(gold_row.get("proof_kind") or last.get("proof_kind") or "")
    stops = [stop_at(timeline, mark, expected, final_classified, proof_kind) for mark in STOP_BUDGETS]
    return {
        "gold_id": gold_row.get("gold_id"),
        "proof_kind": proof_kind,
        "source": "coverage_v3_last_budget_replay",
        "variant": last.get("variant"),
        "replay_of_observed_path": True,
        "documents_expected": expected,
        "final_classified": final_classified,
        "leftover_relevant_at_end": last.get("unresolved_relevant_documents") or [],
        "budget_exhausted_documents_at_end": last.get("budget_exhausted_documents"),
        "stops": stops,
        "budget_exhausted_is_not_absent": True,
    }


def stop_at(
    timeline: list[dict[str, object]],
    stop_budget: int,
    expected: int,
    final_classified: int,
    proof_kind: str,
) -> dict[str, object]:
    observed = _at_or_before(timeline, stop_budget)
    if observed is None:
        return {
            "stop_budget": stop_budget,
            "observed_classified": None,
            "investigation_result": INVESTIGATION_FAILED,
            "replay_of_observed_path": True,
        }
    counts = dict(observed.get("status_counts") or {})
    leftover = list(observed.get("unresolved_relevant") or [])
    jev_yes = int(observed.get("documents_found") or 0)
    complete = expected - len(leftover)
    decided = int(counts.get("EVIDENCE_FOUND") or 0) + int(counts.get("VERIFIED_ABSENT") or 0)
    examined = sum(int(value) for value in counts.values())
    unresolved = examined - decided
    next_yes = _next_gain(timeline, observed, "jev_yes")
    next_complete = _next_gain(timeline, observed, "complete", expected=expected)
    result = INVESTIGATION_COMPLETE if unresolved == 0 and not leftover else INVESTIGATION_PARTIAL
    return {
        "stop_budget": stop_budget,
        "observed_classified": observed.get("classified"),
        "phase": observed.get("phase"),
        "jev_yes_documents": jev_yes,
        "complete_evidence_documents": complete,
        "documents_expected": expected,
        "unresolved_documents": unresolved,
        "unresolved_relevant_documents": leftover,
        "saved_classifications": final_classified - int(observed.get("classified") or 0),
        "investigation_result": result,
        "gold_complete_is_not_system_complete": True,
        "unresolved_kinds": _unresolved_kinds(counts, leftover, proof_kind),
        "status_counts": counts,
        "next_jev_yes": next_yes,
        "next_complete_evidence": next_complete,
        "budget_exhausted_is_not_absent": True,
        "replay_of_observed_path": True,
    }


def run_stop_replay(*, coverage_v3_path: Path | None = None) -> dict[str, object]:
    coverage = json.loads((coverage_v3_path or DEFAULT_V3).read_text(encoding="utf-8"))
    golds = [replay_gold(item) for item in coverage.get("golds") or []]
    return {
        "operation": "coverage",
        "experiment": "workspace_stop_replay_v1",
        "coverage_v3_unchanged": True,
        "classify_unchanged": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_stop_rule": True,
        "replay_of_observed_path": True,
        "budget_exhausted_is_not_absent": True,
        "investigation_results": [
            INVESTIGATION_COMPLETE,
            INVESTIGATION_PARTIAL,
            INVESTIGATION_FAILED,
        ],
        "unresolved_kinds": list(UNRESOLVED_KINDS),
        "stop_budgets": list(STOP_BUDGETS),
        "golds": golds,
    }


def _at_or_before(
    timeline: list[dict[str, object]], stop_budget: int
) -> dict[str, object] | None:
    chosen = None
    for point in timeline:
        if int(point.get("classified") or 0) <= stop_budget:
            chosen = point
    return chosen


def _next_gain(
    timeline: list[dict[str, object]],
    observed: dict[str, object],
    kind: str,
    *,
    expected: int = 0,
) -> dict[str, object] | None:
    start = int(observed.get("classified") or 0)
    start_value = _point_value(observed, kind, expected)
    for point in timeline:
        classified = int(point.get("classified") or 0)
        if classified <= start:
            continue
        value = _point_value(point, kind, expected)
        gained = value - start_value
        if gained <= 0:
            continue
        cost = classified - start
        return {
            "classified": classified,
            "phase": point.get("phase"),
            "new_documents": gained,
            "classifications_until_next": cost,
            "cost_per_new_document": cost / gained,
        }
    return None


def _point_value(point: dict[str, object], kind: str, expected: int) -> int:
    if kind == "jev_yes":
        return int(point.get("documents_found") or 0)
    leftover = list(point.get("unresolved_relevant") or [])
    return expected - len(leftover)


def _unresolved_kinds(
    counts: dict[str, object], leftover: list[str], proof_kind: str
) -> dict[str, int]:
    insufficient = sum(
        int(counts.get(status) or 0)
        for status in ("UNEXAMINED", "RETRIEVED", "NO_EVIDENCE_YET", "BUDGET_EXHAUSTED")
    )
    needs = int(counts.get("NEEDS_ANALYSIS") or 0)
    if proof_kind == "COMPOSITE":
        composite = len(leftover)
        unclear = max(0, needs - composite)
    else:
        composite = 0
        unclear = needs
    return {
        "insufficiently_examined": insufficient,
        "unclear_or_conflicting": unclear,
        "composite_incomplete": composite,
    }
