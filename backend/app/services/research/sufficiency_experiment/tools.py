"""Allowlisted typed workflows. Search and database tools are rejected."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    ProvenanceEvent,
)

ALLOWED_WORKFLOWS = frozenset(
    {
        "segment_passages",
        "evaluate_passages",
        "aggregate_need",
        "quality_gate",
    }
)
FORBIDDEN_TOOLS = frozenset(
    {
        "search",
        "web_search",
        "database",
        "sql",
        "session",
        "http",
        "shell",
        "spawn_agent",
        "spawn_workers",
    }
)

WorkflowFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class UnknownWorkflowToolError(ValueError):
    """The agent asked for a tool that is not an allowlisted workflow."""


class RecursionLimitError(ValueError):
    """A typed workflow tried to re-enter beyond the narrative depth cap."""


async def invoke_workflow(
    name: str,
    payload: Mapping[str, Any],
    registry: Mapping[str, WorkflowFn],
    *,
    depth: int,
    config: ExperimentConfig,
    parent: str | None = None,
) -> tuple[dict[str, Any], ProvenanceEvent]:
    if name in FORBIDDEN_TOOLS or name not in ALLOWED_WORKFLOWS:
        raise UnknownWorkflowToolError(f"tool {name!r} is not an allowlisted workflow")
    if name not in registry:
        raise UnknownWorkflowToolError(f"allowlisted workflow {name!r} is not bound")
    if depth >= config.max_narrative_depth:
        raise RecursionLimitError("narrative recursion limit exceeded")
    result = await registry[name](dict(payload))
    event = ProvenanceEvent(
        workflow=name,
        input_hash=_hash_payload(payload),
        output_hash=_hash_payload(result),
        parent=parent,
    )
    return result, event


def _hash_payload(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
