"""SWE definition matches the swe_bridge map / decision pattern."""

from __future__ import annotations

from app.services.research.sufficiency_experiment.workflow import (
    HANDLER_NAMES,
    compile_sufficiency_workflow,
)


def test_sufficiency_workflow_compiles() -> None:
    compiled = compile_sufficiency_workflow()
    assert compiled.name == "evidence_sufficiency"
    nodes = compiled.document["nodes"]
    assert nodes["jobs"]["type"] == "map"
    assert nodes["jobs"]["child"] == "evaluate_one"
    assert nodes["evaluate_one"]["handler"] == "sufficiency.evaluate_one"
    assert nodes["finish_gate"]["evaluator"] == "expression"
    assert nodes["finish_gate"]["routes"]["true"] == "emit"
    assert nodes["aggregate"]["next"] == "prepare_pairs"
    assert nodes["pair_jobs"]["type"] == "map"
    assert nodes["pair_jobs"]["child"] == "evaluate_pair"
    assert nodes["aggregate_pairs"]["next"] == "gap_review"
    assert nodes["gap_review"]["next"] == "route"
    assert nodes["finish_gate"]["routes"]["false"] == "escalate_gate"
    assert "sub_gate" not in nodes
    assert "resolve" not in nodes
    assert HANDLER_NAMES == {
        "sufficiency.prepare",
        "sufficiency.evaluate_one",
        "sufficiency.aggregate",
        "sufficiency.prepare_pairs",
        "sufficiency.evaluate_pair",
        "sufficiency.aggregate_pairs",
        "sufficiency.gap_review",
        "sufficiency.route",
        "sufficiency.narrative",
        "sufficiency.emit",
    }
