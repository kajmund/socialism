"""Validate parent-supplied JSON Schema and worker JSON against it."""

from __future__ import annotations

from typing import Any


def schema_error(schema: object) -> str | None:
    if not isinstance(schema, dict) or "type" not in schema:
        return "invalid_output_schema"
    return None


def instance_matches(schema: dict[str, Any], value: object) -> bool:
    expected = schema.get("type")
    if expected == "object":
        return _object_matches(schema, value)
    if expected == "array":
        return _array_matches(schema, value)
    checkers = {
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    check = checkers.get(expected)
    return False if check is None else check(value)


def _object_matches(schema: dict[str, Any], value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = schema.get("required") or []
    if any(key not in value for key in required):
        return False
    properties = schema.get("properties") or {}
    return all(
        instance_matches(properties[key], item)
        for key, item in value.items()
        if key in properties
    )


def _array_matches(schema: dict[str, Any], value: object) -> bool:
    if not isinstance(value, list):
        return False
    items = schema.get("items")
    if not isinstance(items, dict):
        return True
    return all(instance_matches(items, item) for item in value)
