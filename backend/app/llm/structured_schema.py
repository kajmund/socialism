"""Cerebras-strict JSON Schema derived from Pydantic `model_json_schema()`."""

from __future__ import annotations

import copy
from typing import Any, cast

# Constrained decoding rejects these JSON Schema keywords.
_UNSUPPORTED_STRICT_KEYS = frozenset(
    {
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "format",
    }
)


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    root = copy.deepcopy(schema)
    return _ensure_strict(root, root)


def _ensure_strict(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    defs = node.get("$defs")
    if isinstance(defs, dict):
        for name, definition in defs.items():
            if isinstance(definition, dict):
                defs[name] = _ensure_strict(definition, root)

    definitions = node.get("definitions")
    if isinstance(definitions, dict):
        for name, definition in definitions.items():
            if isinstance(definition, dict):
                definitions[name] = _ensure_strict(definition, root)

    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False

    properties = node.get("properties")
    if isinstance(properties, dict):
        node["required"] = list(properties)
        node["properties"] = {
            key: _ensure_strict(value, root) if isinstance(value, dict) else value
            for key, value in properties.items()
        }

    items = node.get("items")
    if isinstance(items, dict):
        node["items"] = _ensure_strict(items, root)

    any_of = node.get("anyOf")
    if isinstance(any_of, list):
        node["anyOf"] = [
            _ensure_strict(variant, root) if isinstance(variant, dict) else variant
            for variant in any_of
        ]

    all_of = node.get("allOf")
    if isinstance(all_of, list):
        if len(all_of) == 1 and isinstance(all_of[0], dict):
            node.update(_ensure_strict(all_of[0], root))
            node.pop("allOf", None)
        else:
            node["allOf"] = [
                _ensure_strict(entry, root) if isinstance(entry, dict) else entry
                for entry in all_of
            ]

    if "default" in node and node["default"] is None:
        node.pop("default")

    for key in _UNSUPPORTED_STRICT_KEYS:
        node.pop(key, None)

    ref = node.get("$ref")
    if isinstance(ref, str) and len(node) > 1:
        resolved = copy.deepcopy(_resolve_ref(root, ref))
        combined = {
            **resolved,
            **{key: value for key, value in node.items() if key != "$ref"},
        }
        return _ensure_strict(combined, root)

    return node


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"Unexpected $ref format {ref!r}")
    current: object = root
    for key in ref[2:].split("/"):
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Unresolved $ref {ref!r}")
        current = current[key]
    if not isinstance(current, dict):
        raise ValueError(f"$ref {ref!r} did not resolve to an object")
    return cast(dict[str, Any], current)
