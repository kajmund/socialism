"""Unit tests for prompt configuration benchmark helpers."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_prompt_configurations.py"
spec = importlib.util.spec_from_file_location("benchmark_prompt_configurations", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_baseline_action_rules_contains_asymmetric_like_guidance():
    text = mod.baseline_action_rules("sv")
    assert "Gilla (like_post / like_comment) BARA när du faktiskt stöder" in text
    assert mod._SYMMETRIC_LIKE_RULE not in text


def test_symmetric_like_inserts_encouragement_rule():
    text = mod.build_action_rules_variant("symmetric_like")
    assert mod._SYMMETRIC_LIKE_RULE in text
    assert mod._OLD_STRUCTURE_LINE in text


def test_symmetric_list_changes_structure_and_like_rule():
    text = mod.build_action_rules_variant("symmetric_list")
    assert mod._SYMMETRIC_LIKE_RULE in text
    assert mod._NEW_STRUCTURE_LINE in text
    assert mod._OLD_STRUCTURE_LINE not in text
    assert "kort instämmande/avståndstagande" not in text


def test_list_only_changes_structure_without_like_rule():
    text = mod.build_action_rules_variant("list_only")
    assert mod._SYMMETRIC_LIKE_RULE not in text
    assert mod._NEW_STRUCTURE_LINE in text


def test_engagement_from_histogram_like_ratio():
    hist = [
        {"action": "like_post", "count": 4},
        {"action": "dislike_post", "count": 2},
        {"action": "create_comment", "count": 10},
    ]
    out = mod.engagement_from_histogram(
        hist, agent_count=5, gini=0.42, zero_like_agents=2, comments=10
    )
    assert out["like_count"] == 4
    assert out["dislike_count"] == 2
    assert out["like_ratio"] == pytest.approx(4 / 6)
    assert out["reaction_count"] == 16
    assert out["zero_engagement_share"] == pytest.approx(0.4)


def test_aggregate_numeric_mean_std():
    agg = mod.aggregate_numeric([0.4, 0.5, 0.6])
    assert agg["n"] == 3
    assert agg["mean"] == pytest.approx(0.5)
    assert agg["min"] == pytest.approx(0.4)
    assert agg["max"] == pytest.approx(0.6)


def test_critical_retention_ok():
    assert mod.critical_retention_ok(
        candidate_mean=0.21, baseline_mean=0.30, retention=0.70
    )
    assert not mod.critical_retention_ok(
        candidate_mean=0.20, baseline_mean=0.30, retention=0.70
    )


def _result(
    variant: str,
    *,
    like_ratio: float | None,
    critical: float | None,
    rep: int = 1,
) -> mod.PromptBenchmarkResult:
    return mod.PromptBenchmarkResult(
        variant=variant,
        configuration_id=1,
        configuration_name=variant,
        repetition=rep,
        wall_seconds=1.0,
        status="ok",
        error=None,
        variants=1,
        ticks_run=2,
        agent_count=10,
        trace_events=5,
        posts=3,
        comments=8,
        action_histogram=[],
        like_count=0,
        dislike_count=0,
        reaction_count=20,
        like_ratio=like_ratio,
        zero_engagement_agents=0,
        zero_engagement_share=0.0,
        gini=0.5,
        critical_tone_share=critical,
    )


def test_determine_conclusion_winner_when_like_up_and_critical_retained():
    baseline_runs = [_result("baseline", like_ratio=0.2, critical=0.30, rep=i) for i in range(1, 4)]
    candidate_runs = [
        _result("symmetric_like", like_ratio=0.45, critical=0.25, rep=i) for i in range(1, 4)
    ]
    aggregates = [
        mod.aggregate_variant_results(baseline_runs),
        mod.aggregate_variant_results(candidate_runs),
    ]
    conclusion = mod.determine_conclusion(aggregates, critical_retention=0.70)
    assert conclusion["conclusion"] == "winner"
    assert conclusion["winner"] == "symmetric_like"


def test_determine_conclusion_no_winner_when_critical_drops_too_much():
    baseline_runs = [_result("baseline", like_ratio=0.2, critical=0.30)]
    candidate_runs = [_result("symmetric_like", like_ratio=0.5, critical=0.05)]
    aggregates = [
        mod.aggregate_variant_results(baseline_runs),
        mod.aggregate_variant_results(candidate_runs),
    ]
    conclusion = mod.determine_conclusion(aggregates, critical_retention=0.70)
    assert conclusion["conclusion"] == "no_clear_result"


def test_detect_overcorrection_flags_low_critical_tone():
    baseline = mod.PromptBenchmarkResult(
        variant="baseline",
        configuration_id=1,
        configuration_name="Baseline",
        repetition=1,
        wall_seconds=1.0,
        status="ok",
        error=None,
        variants=1,
        ticks_run=2,
        agent_count=10,
        trace_events=5,
        posts=3,
        comments=8,
        action_histogram=[],
        like_count=0,
        dislike_count=5,
        reaction_count=5,
        like_ratio=0.0,
        zero_engagement_agents=8,
        zero_engagement_share=0.8,
        gini=0.5,
        critical_tone_share=0.30,
    )
    candidate = mod.PromptBenchmarkResult(
        variant="symmetric_like",
        configuration_id=2,
        configuration_name="Sym",
        repetition=1,
        wall_seconds=1.0,
        status="ok",
        error=None,
        variants=1,
        ticks_run=2,
        agent_count=10,
        trace_events=5,
        posts=3,
        comments=8,
        action_histogram=[],
        like_count=10,
        dislike_count=1,
        reaction_count=20,
        like_ratio=0.91,
        zero_engagement_agents=2,
        zero_engagement_share=0.2,
        gini=0.12,
        critical_tone_share=0.02,
        sarcasm_style_share=0.0,
    )
    warnings = mod.detect_overcorrection_warnings(candidate, baseline=baseline)
    assert any("critical_tone_share" in w for w in warnings)
    assert any("gini unusually low" in w for w in warnings)


def test_apply_boost_rounds_multiplies_in_memory():
    from types import SimpleNamespace

    run = SimpleNamespace(
        main_ticks=[{"key": "t1", "rounds": 2}, {"key": "t2", "rounds": 1}],
        branch={"a": [{"key": "ta", "rounds": 1}]},
    )
    mod.apply_boost_rounds(run, 3)
    assert run.main_ticks[0]["rounds"] == 6
    assert run.main_ticks[1]["rounds"] == 3
    assert run.branch["a"][0]["rounds"] == 3
