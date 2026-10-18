"""Mechanics and frozen observations for the Step A parity harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.channel_parity_experiment.adapters import capture_case
from scripts.channel_parity_experiment.runner import run_experiment
from scripts.document_presentation_benchmark.cases import build_gold_cases

BASELINE = (
    Path(__file__).parent
    / "integration/baselines/channel-parity-step-a-v1.json"
)


@pytest.mark.asyncio
async def test_all_gold_cases_run_through_all_three_adapters():
    cases = build_gold_cases()
    result = await run_experiment()

    assert {case.intent for case in cases} == {
        "show",
        "count",
        "analyze",
        "ambiguous",
    }
    assert {case.mode for case in cases} == {
        "replace",
        "filter",
        "within",
        "extend",
    }
    assert result["summary"]["gold_cases"] == 50
    assert result["summary"]["channel_executions"] == 150
    assert result["summary"]["semantic_parity"] == 150
    assert result["summary"]["semantic_parity_target"] == 150
    assert result["summary"]["incorrect_auto_displays"] == 0
    assert result["summary"]["wrong_selections_or_modes"] == 0
    assert result["summary"]["duplicates"] == 0


@pytest.mark.asyncio
async def test_normalization_happens_after_distinct_transport_capture():
    case = next(case for case in build_gold_cases() if case.expected_gallery)
    text = await capture_case(case, "text")
    voice = await capture_case(case, "voice")
    group = await capture_case(case, "group")

    assert text.raw_events[0]["type"] == "workspace_tool"
    assert voice.raw_events[0]["type"] == "workspace.tool"
    assert group.raw_events[0]["type"] == "workspace.tool"
    assert text.raw_events[0]["request_id"] == "deterministic-turn"
    assert voice.raw_events[0]["turn_id"] == "deterministic-turn"
    assert "turn_id" not in group.raw_events[0]


@pytest.mark.asyncio
async def test_current_safety_gaps_are_results_not_expected_failures():
    result = await run_experiment()
    summary = result["summary"]

    assert summary["missing_turn_ids"] == 25
    assert summary["non_floor_presentations"] == 1
    assert summary["late_after_cancel"] == {"voice": 1, "group": 1}
    assert result["approved_for_step_b"] is False


@pytest.mark.asyncio
async def test_frozen_baseline_matches_current_capture():
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert await run_experiment() == expected
