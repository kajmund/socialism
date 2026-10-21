"""Reject reserved SWD features before a run starts."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Callable
from typing import Any

from app.swe.runtime_errors import SwePreflightError, SweUnsupportedError

UNSUPPORTED_TYPES = frozenset({"wait", "subworkflow"})


def assert_handlers_registered(
    document: Mapping[str, Any],
    handlers: Mapping[str, Callable[..., Any]],
) -> None:
    nodes = document["nodes"]
    for node_id, node in nodes.items():
        if node["type"] != "task":
            continue
        name = node["handler"]
        if name not in handlers:
            raise SwePreflightError(
                f"unregistered handler {name!r}",
                path=f"nodes.{node_id}.handler",
            )


def assert_phase2_supported(document: Mapping[str, Any]) -> None:
    for node_id, node in document["nodes"].items():
        node_type = node["type"]
        if node_type in UNSUPPORTED_TYPES:
            raise SweUnsupportedError(
                f"{node_type} nodes are not executable in SWE phase 2",
                path=f"nodes.{node_id}.type",
            )
        if node_type == "decision" and node.get("evaluator") == "provider":
            raise SweUnsupportedError(
                "decision provider evaluators are not executable in SWE phase 2",
                path=f"nodes.{node_id}.evaluator",
            )
        if node.get("retry") is not None:
            raise SweUnsupportedError(
                "retry is not executable in SWE phase 2",
                path=f"nodes.{node_id}.retry",
            )
        if node.get("cache_policy") == "exact":
            raise SweUnsupportedError(
                "cache_policy exact is not executable in SWE phase 2",
                path=f"nodes.{node_id}.cache_policy",
            )
