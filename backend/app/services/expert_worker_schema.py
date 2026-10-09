"""Validate parent-supplied JSON Schema and worker JSON against it."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


def schema_error(schema: object) -> str | None:
    if not isinstance(schema, dict) or _remote_keyword(schema):
        return "invalid_output_schema"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return "invalid_output_schema"
    return None


def instance_matches(schema: dict[str, Any], value: object) -> bool:
    if schema_error(schema) is not None:
        return False
    return Draft202012Validator(schema).is_valid(value)


def _remote_keyword(value: object) -> bool:
    if isinstance(value, dict):
        if "$ref" in value or "$schema" in value:
            return True
        return any(_remote_keyword(item) for item in value.values())
    if isinstance(value, list):
        return any(_remote_keyword(item) for item in value)
    return False
