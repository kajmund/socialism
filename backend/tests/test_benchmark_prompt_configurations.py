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
    out = mod.engagement_from_histogram(hist, agent_count=5, gini=0.42, zero_like_agents=2)
    assert out["like_count"] == 4
    assert out["dislike_count"] == 2
    assert out["like_ratio"] == pytest.approx(4 / 6)
    assert out["zero_engagement_share"] == pytest.approx(0.4)


def test_detect_overcorrection_flags_low_critical_tone():
    baseline = mod.PromptBenchmarkResult(
        variant="baseline",
        configuration_id=1,
        configuration_name="Baseline",
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


def test_rank_results_prefers_balanced_like_ratio():
    rows = [
        mod.PromptBenchmarkResult(
            variant="baseline",
            configuration_id=1,
            configuration_name="Baseline",
            wall_seconds=1.0,
            status="ok",
            error=None,
            variants=1,
            ticks_run=1,
            agent_count=5,
            trace_events=1,
            posts=1,
            comments=1,
            action_histogram=[],
            like_count=0,
            dislike_count=1,
            like_ratio=0.0,
            zero_engagement_agents=4,
            zero_engagement_share=0.8,
            gini=0.5,
            critical_tone_share=0.25,
        ),
        mod.PromptBenchmarkResult(
            variant="symmetric_like",
            configuration_id=2,
            configuration_name="Sym",
            wall_seconds=1.0,
            status="ok",
            error=None,
            variants=1,
            ticks_run=1,
            agent_count=5,
            trace_events=1,
            posts=1,
            comments=1,
            action_histogram=[],
            like_count=3,
            dislike_count=2,
            like_ratio=0.6,
            zero_engagement_agents=2,
            zero_engagement_share=0.4,
            gini=0.45,
            critical_tone_share=0.20,
        ),
    ]
    ranked = mod.rank_results(rows)
    assert ranked[0].variant == "symmetric_like"
