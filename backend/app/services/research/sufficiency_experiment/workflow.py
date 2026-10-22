"""SWE definition for the sufficiency experiment.

Mirrors `swe_bridge._workflow`: task / map / expression decision / end.
Execution is `WorkflowRunner`, not a Python orchestration loop.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from app.swe.definition import CompiledDefinition, compile_definition

HANDLER_NAMES = frozenset(
    {
        "sufficiency.prepare",
        "sufficiency.evaluate_one",
        "sufficiency.aggregate",
        "sufficiency.route",
        "sufficiency.narrative",
        "sufficiency.emit",
    }
)

_WORKFLOW_LIMITS = {"max_steps": 2_000, "max_depth": 6, "timeout_seconds": 1_800}


def _document(concurrency: int) -> dict[str, Any]:
    return {
        "version": "1.0",
        "name": "evidence_sufficiency",
        "entrypoint": "prepare",
        "limits": dict(_WORKFLOW_LIMITS),
        "nodes": {
            "prepare": {
                "type": "task",
                "handler": "sufficiency.prepare",
                "next": "programmatic_gate",
            },
            "programmatic_gate": {
                "type": "decision",
                "evaluator": "expression",
                "condition": {
                    "eq": [{"var": "$.prepare.result.done"}, {"const": True}]
                },
                "routes": {"true": "emit", "false": "jobs"},
            },
            "jobs": {
                "type": "map",
                "items": "$.prepare.result.jobs",
                "child": "evaluate_one",
                "concurrency": concurrency,
                "next": "aggregate",
            },
            "evaluate_one": {"type": "task", "handler": "sufficiency.evaluate_one"},
            "aggregate": {
                "type": "task",
                "handler": "sufficiency.aggregate",
                "next": "route",
            },
            "route": {
                "type": "task",
                "handler": "sufficiency.route",
                "next": "finish_gate",
            },
            "finish_gate": {
                "type": "decision",
                "evaluator": "expression",
                "condition": {
                    "eq": [{"var": "$.route.result.finish"}, {"const": True}]
                },
                "routes": {"true": "emit", "false": "escalate_gate"},
            },
            "escalate_gate": {
                "type": "decision",
                "evaluator": "expression",
                "condition": {
                    "eq": [{"var": "$.route.result.escalate"}, {"const": True}]
                },
                "routes": {"true": "narrative", "false": "emit"},
            },
            "narrative": {
                "type": "task",
                "handler": "sufficiency.narrative",
                "next": "emit",
            },
            "emit": {"type": "task", "handler": "sufficiency.emit", "next": "done"},
            "done": {"type": "end", "status": "completed"},
        },
    }


@cache
def compile_sufficiency_workflow(concurrency: int = 8) -> CompiledDefinition:
    return compile_definition(_document(concurrency), handlers=HANDLER_NAMES)
