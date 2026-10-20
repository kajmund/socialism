"""Compile SWD fixtures for runtime tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.swe.definition import CompiledDefinition, compile_definition

DEFAULT_LIMITS = {"max_steps": 80, "max_depth": 4, "timeout_seconds": 30}


def compile_runtime(
    nodes: Mapping[str, Any],
    *,
    name: str = "fixture",
    entrypoint: str = "start",
    limits: Mapping[str, int] | None = None,
    handlers: frozenset[str] | None = None,
) -> CompiledDefinition:
    document = {
        "version": "1.0",
        "name": name,
        "entrypoint": entrypoint,
        "limits": dict(limits or DEFAULT_LIMITS),
        "nodes": dict(nodes),
    }
    return compile_definition(document, handlers=handlers)
