"""A2 replay: a forced contradiction survives a measured duplicate score."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.research.sufficiency_experiment.golden import (
    scripted_benchmark_cases,
)
from app.services.research.sufficiency_experiment.replay import replay_case

BASELINES = Path(__file__).resolve().parent / "integration" / "baselines"
TRACE = BASELINES / "sufficiency-contradiction-trace-v1.json"
REPLAY = BASELINES / "sufficiency-conflict-replay-v1.json"


def _traces() -> dict[str, dict[str, Any]]:
    payload = json.loads(TRACE.read_text(encoding="utf-8"))
    return {case["case_id"]: case["trace"] for case in payload["cases"]}


def _cases() -> dict[str, Any]:
    return {case.case_id: case for case in scripted_benchmark_cases()}


def test_forced_contradiction_survives_high_duplicate_score() -> None:
    traces = _traces()
    cases = _cases()
    for case_id in ("tail_counterevidence", "late_evidence"):
        row = replay_case(cases[case_id], traces[case_id])
        assert row["draft_result"] == "insufficient"
        assert row["gate_allows_sufficient"] is False
        assert row["unresolved_conflicts"]
        assert row["duplicate_scores"]
        assert max(row["duplicate_scores"]) >= 0.6
        statuses = {conflict["status"] for conflict in row["conflicts"]}
        assert statuses == {"unresolved"}
        assert all(conflict["resolution"] is None for conflict in row["conflicts"])


def test_untouched_control_stays_sufficient() -> None:
    row = replay_case(_cases()["short_sufficient"], _traces()["short_sufficient"], force=False)
    assert row["forced_passage_ids"] == []
    assert row["draft_result"] == "sufficient"


def test_replay_artifact_matches_current_rules() -> None:
    artifact = json.loads(REPLAY.read_text(encoding="utf-8"))
    traces = _traces()
    cases = _cases()
    assert artifact["measurement"] == "counterfactual_replay"
    expected = {row["case_id"]: row for row in artifact["cases"]}
    for case_id, recorded in expected.items():
        case = cases[case_id]
        live = replay_case(case, traces[case_id], force=case.expected == "insufficient")
        assert live["draft_result"] == recorded["draft_result"]
        assert live["status"] == recorded["status"]
        assert len(live["unresolved_conflicts"]) == len(recorded["unresolved_conflicts"])
