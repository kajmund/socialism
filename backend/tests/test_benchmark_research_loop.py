"""Baseline harness contract: fake mode only, zero LLM calls, warm answer reuse."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.benchmark_research_loop import _benchmark


@pytest.mark.asyncio
async def test_benchmark_measures_cold_and_warm_without_llm(tmp_path) -> None:
    report = tmp_path / "report.json"
    args = argparse.Namespace(
        runs=1,
        json=str(report),
        data_dir=str(tmp_path / "work"),
    )

    payload = await _benchmark(args)

    summary = payload["summary"]
    assert summary["mode"] == "fake-orchestration-measurement"
    assert summary["llm_calls_total"] == 0
    assert summary["reused_answers_cold"] == 0
    assert summary["reused_answers_warm"] == 1
    assert summary["cold"]["provider_calls"] == 1
    assert summary["warm"]["provider_calls"] == 0
    assert summary["cold"]["median_wall_ms"] > 0
    assert summary["warm"]["median_wall_ms"] > 0

    runs = {row["label"]: row for row in payload["runs"]}
    assert runs["cold"]["status"] == "ready"
    assert runs["warm"]["status"] == "ready"
    assert runs["cold"]["reused_answer_id"] is None
    assert runs["warm"]["reused_answer_id"]
    assert runs["warm"]["reuse_match"] == "exact"
    assert runs["cold"]["needs"] == 2
    assert runs["warm"]["needs"] == 1
    assert runs["cold"]["stop_reason"] == "sufficient"
    assert runs["warm"]["stop_reason"] == "sufficient"

    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["summary"] == summary
