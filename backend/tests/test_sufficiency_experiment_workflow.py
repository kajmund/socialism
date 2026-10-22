"""SWE definition for the sufficiency experiment compiles and routes."""

from __future__ import annotations

from app.services.research.sufficiency_experiment.workflow import (
    HANDLER_NAMES,
    compile_sufficiency_workflow,
)


def test_sufficiency_workflow_compiles() -> None:
    compiled = compile_sufficiency_workflow()
    assert compiled.name == "evidence_sufficiency"
    nodes = compiled.document["nodes"]
    assert nodes["evaluate"]["handler"] == "sufficiency.evaluate"
    assert nodes["escalate_check"]["routes"]["true"] == "narrative"
    assert nodes["escalate_check"]["routes"]["false"] == "end_complete"
    assert HANDLER_NAMES == {
        "sufficiency.programmatic",
        "sufficiency.segment",
        "sufficiency.evaluate",
        "sufficiency.aggregate",
        "sufficiency.quality",
        "sufficiency.narrative",
    }
