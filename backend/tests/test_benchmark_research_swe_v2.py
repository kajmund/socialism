"""Pure helper tests for the v2 measurement harness (no DB, no research run)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from scripts.benchmark_research_swe_v2 import (
    FakeSample,
    Interval,
    Recorder,
    _live_ranking,
    _requested_modes,
    _run_scenario_arm,
    _scenarios,
    dispersion,
    interval_metrics,
)
from scripts.benchmark_research_loop import _install_fake_embeddings


def _interval(name: str, start: float, end: float) -> Interval:
    return Interval(name=name, start=start, end=end)


def _sample(*, run: int, arm: str, question: str, repeat: int,
            wall_ms: float) -> FakeSample:
    busy, sum_ms, needs = 100.0, 200.0, 16
    return FakeSample(
        run_index=run, arm=arm, question_id=question, repeat=repeat,
        wall_ms=wall_ms,
        need_metrics={
            "sum_ms": sum_ms, "busy_union_ms": busy, "span_ms": busy,
            "peak_concurrency": 8, "overhead_ms": 10.0,
            "parallel_gain_ms": max(0.0, sum_ms - busy),
            "span_overhead_ms": max(0.0, wall_ms - busy), "per_name": {},
        },
        handler_metrics={"per_name": {}},
        domain={
            "needs": needs, "found": needs, "not_found": 0,
            "errors": 0, "assessments": [[1, "sufficient"]],
            "completeness": [[1, "complete"]], "quality_rows": needs,
        },
        swe=None, provider_calls=needs, llm_calls=0,
        prompt_tokens=0, completion_tokens=0,
    )


def test_recorder_counts_active_provider_calls_not_coroutine_lifetime() -> None:
    class Source:
        async def research(self, need: object, context: object) -> list[object]:
            await asyncio.sleep(0.02)
            return []

    source = Source()
    recorder = Recorder()
    recorder.wrap_source(source)

    async def run() -> None:
        await asyncio.gather(*(source.research(index, None) for index in range(3)))

    asyncio.run(run())
    recorder.restore_source()
    assert recorder.provider_peak == 3


def test_requested_modes_accepts_comma_lists() -> None:
    assert _requested_modes("fake,parity") == {"fake", "parity"}
    assert _requested_modes("all") == {"fake", "parity", "live"}
    assert _requested_modes("parity") == {"parity"}


def test_scenarios_expose_fresh_fixture_factories() -> None:
    for scenario in _scenarios():
        for key in ("assessor", "follow_up"):
            value = scenario.get(key)
            if value is None:
                continue
            assert callable(value), f"{scenario['name']}: {key} must be a factory"
            first = value()
            second = value()
            assert first is not second, f"{scenario['name']}: {key} is shared"


@pytest.mark.integration
def test_follow_up_wave_snapshots_equal_across_arms() -> None:
    import app.services.research.composition as composition

    scenario = next(row for row in _scenarios() if row["name"] == "follow_up_wave")
    root = Path(tempfile.mkdtemp(prefix="v2-parity-test-"))
    original = _install_fake_embeddings()

    async def run() -> dict[str, dict]:
        snapshots: dict[str, dict] = {}
        for arm in ("baseline", "swe_a", "swe_b"):
            snapshots[arm] = await _run_scenario_arm(
                arm=arm, scenario=scenario, source=scenario["source"](),
                root=root, llm_calls=[],
            )
        return snapshots

    try:
        snapshots = asyncio.run(run())
    finally:
        composition.research_embeddings = original
    baseline = snapshots["baseline"]
    for arm in ("swe_a", "swe_b"):
        for key in (
            "needs", "wave", "assessments", "evidence", "found",
            "quality_rows", "progress_event_types",
        ):
            assert snapshots[arm].get(key) == baseline.get(key), (
                f"{arm}.{key} differs from baseline"
            )


def test_interval_metrics_peak_concurrency_and_busy_union() -> None:
    intervals = [
        _interval("a", 0.0, 0.2),
        _interval("b", 0.05, 0.25),
        _interval("c", 0.1, 0.3),
        _interval("d", 0.5, 0.6),
    ]
    metrics = interval_metrics(intervals, wall_ms=800.0)
    assert metrics["peak_concurrency"] == 3
    assert metrics["busy_union_ms"] == 400.0
    assert metrics["span_ms"] == 600.0
    assert metrics["sum_ms"] == 700.0
    assert metrics["overhead_ms"] == 400.0


def test_interval_metrics_empty_is_full_overhead() -> None:
    metrics = interval_metrics([], wall_ms=123.4)
    assert metrics["peak_concurrency"] == 0
    assert metrics["busy_union_ms"] == 0.0
    assert metrics["overhead_ms"] == 123.4


def test_dispersion_reports_spread_and_per_question_medians() -> None:
    samples = [
        _sample(run=0, arm="baseline", question="q1", repeat=0, wall_ms=800.0),
        _sample(run=0, arm="swe_a", question="q1", repeat=0, wall_ms=840.0),
        _sample(run=1, arm="baseline", question="q1", repeat=0, wall_ms=820.0),
        _sample(run=1, arm="swe_a", question="q1", repeat=0, wall_ms=900.0),
        _sample(run=0, arm="swe_b", question="q2", repeat=1, wall_ms=700.0),
        _sample(run=1, arm="swe_b", question="q2", repeat=1, wall_ms=760.0),
    ]
    result = dispersion(samples, runs=2)
    assert result["baseline"]["per_run_median_stats"]["min"] == 800.0
    assert result["swe_a"]["ratio_per_run"]["min"] == 1.05
    assert result["swe_a"]["ratio_per_run"]["max"] == 1.0976
    assert result["swe_a"]["per_question_median_ms"]["q1"] == 870.0
    assert result["swe_b"]["peak_concurrency"]["max"] == 8


def test_live_ranking_never_calls_a_faster_lower_evidence_run_better() -> None:
    samples = [
        {"arm": "baseline", "wall_ms": 1000.0, "prompt_tokens": 100,
         "completion_tokens": 50,
         "evidence": [{"status": "found"}] * 4,
         "needs": [{"need_id": "n"}] * 2,
         "assessments": ["sufficient"], "completeness": ["complete"],
         "judge": {"rubric": {"coverage": 3, "citation_support": 3,
                              "contradiction_handling": 3, "answer_readiness": 3}}},
        {"arm": "swe_b", "wall_ms": 500.0, "prompt_tokens": 60,
         "completion_tokens": 30,
         "evidence": [{"status": "found"}, {"status": "not_found"},
                      {"status": "not_found"}, {"status": "not_found"}],
         "needs": [{"need_id": "n"}] * 2,
         "assessments": ["insufficient"], "completeness": ["incomplete"],
         "judge": {"rubric": {"coverage": 1, "citation_support": 1,
                              "contradiction_handling": 1, "answer_readiness": 1}}},
    ]
    ranking = _live_ranking(samples)
    classification = ranking["classification"]["swe_b"]
    assert classification["faster_than_baseline"] is True
    assert classification["quality_not_worse_than_baseline"] is False
    assert classification["label"] == "faster but lower evidence — not better"
