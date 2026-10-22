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
    assert nodes["sub_gate"]["routes"]["true"] == "resolve"
    assert nodes["resolve"]["next"] == "aggregate"
    assert HANDLER_NAMES == {
        "sufficiency.prepare",
        "sufficiency.evaluate_one",
        "sufficiency.aggregate",
        "sufficiency.route",
        "sufficiency.resolve",
        "sufficiency.narrative",
        "sufficiency.emit",
    }
