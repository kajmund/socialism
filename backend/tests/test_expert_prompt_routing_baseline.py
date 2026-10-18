"""Frozen prompt-routing headlines protect the measured split."""

import json
from pathlib import Path

from app.services.prompt_catalog import default_prompts

BASELINES = Path(__file__).parent / "integration/baselines"


def _baseline(version: str) -> dict:
    return json.loads(
        (BASELINES / f"expert-prompt-routing-{version}.json").read_text()
    )


def test_prompt_split_headline_does_not_regress():
    before = _baseline("v1")
    after = _baseline("v2")
    assert before["do_not_overwrite"] is True
    assert after["do_not_overwrite"] is True
    assert (
        after["headline"]["top1_tool_accuracy"]
        >= before["headline"]["top1_tool_accuracy"]
    )
    assert (
        after["headline"]["find_show_chain_rate"]
        >= before["headline"]["find_show_chain_rate"]
    )
    assert after["headline"]["smalltalk_no_tool_rate"] == 1.0


def test_active_defaults_match_the_measured_prompt_size():
    prompts = default_prompts("sv")
    measured = _baseline("v2")["headline"]
    assert len(prompts["workspace.voice.system"]) == measured["system_chars"]
    assert len(prompts["workspace.chat.turn"]) == measured["turn_chars"]


def test_find_show_latency_baseline_preserves_the_handoff_boundary():
    measured = json.loads(
        (BASELINES / "expert-find-show-e2e-v1.json").read_text()
    )
    assert measured["do_not_overwrite"] is True
    assert measured["quality"]["show_document_set_successes"] == 5
    assert measured["quality"]["samples"] == 5
    assert measured["calls_per_sample"] == {
        "llm": 2,
        "jev": 2,
        "embedding": 0,
        "overgraph_category_lookup": 1,
    }
    assert measured["frontend_render_included"] is False
