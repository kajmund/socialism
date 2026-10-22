"""SWE definition and handler binding for the sufficiency experiment."""

from __future__ import annotations

from typing import Any

from app.swe.definition import CompiledDefinition, compile_definition

HANDLER_NAMES = frozenset(
    {
        "sufficiency.programmatic",
        "sufficiency.segment",
        "sufficiency.evaluate",
        "sufficiency.aggregate",
        "sufficiency.quality",
        "sufficiency.narrative",
    }
)

SUFFICIENCY_WORKFLOW: dict[str, Any] = {
    "version": "1.0",
    "name": "evidence_sufficiency",
    "entrypoint": "programmatic",
    "limits": {"max_steps": 40, "max_depth": 4, "timeout_seconds": 1800},
    "nodes": {
        "programmatic": {
            "type": "task",
            "handler": "sufficiency.programmatic",
            "next": "after_programmatic",
        },
        "after_programmatic": {
            "type": "decision",
            "evaluator": "expression",
            "condition": {
                "eq": [
                    {"var": "$.programmatic.result.done"},
                    {"const": True},
                ]
            },
            "routes": {"true": "end_complete", "false": "segment"},
        },
        "segment": {
            "type": "task",
            "handler": "sufficiency.segment",
            "next": "evaluate",
        },
        "evaluate": {
            "type": "task",
            "handler": "sufficiency.evaluate",
            "next": "aggregate",
        },
        "aggregate": {
            "type": "task",
            "handler": "sufficiency.aggregate",
            "next": "quality",
        },
        "quality": {
            "type": "task",
            "handler": "sufficiency.quality",
            "next": "escalate_check",
        },
        "escalate_check": {
            "type": "decision",
            "evaluator": "expression",
            "condition": {
                "eq": [
                    {"var": "$.quality.result.escalate"},
                    {"const": True},
                ]
            },
            "routes": {"true": "narrative", "false": "end_complete"},
        },
        "narrative": {
            "type": "task",
            "handler": "sufficiency.narrative",
            "next": "end_complete",
        },
        "end_complete": {"type": "end", "status": "completed"},
    },
}


def compile_sufficiency_workflow() -> CompiledDefinition:
    return compile_definition(SUFFICIENCY_WORKFLOW, handlers=HANDLER_NAMES)
