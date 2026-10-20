"""SWD 1.0 parse, schema, and graph validation."""

from __future__ import annotations

import copy
import json

import pytest

from jsonschema import Draft202012Validator

from app.swe.canonicalize import sha256_hex
from app.swe.definition import CompiledDefinition, compile_definition, compile_swd_text
from app.swe.errors import SwdValidationError
from app.swe.schema import load_schema
from app.swe.yaml_load import load_swd_json, load_swd_yaml
from tests.swe.helpers import (
    EXAMPLE_HANDLERS,
    EXAMPLE_PROMPT_KEY,
    EXAMPLE_PROVIDERS,
    FIXTURES,
)

EXAMPLE_YAML = FIXTURES / "research_parallel.yaml"
EXAMPLE_JSON = FIXTURES / "research_parallel.json"


def _compile(document: object) -> CompiledDefinition:
    return compile_definition(
        document,
        handlers=EXAMPLE_HANDLERS,
        providers=EXAMPLE_PROVIDERS,
    )


def test_json_schema_is_valid() -> None:
    Draft202012Validator.check_schema(load_schema())


def test_json_and_yaml_have_the_same_hash() -> None:
    json_doc = _compile(load_swd_json(EXAMPLE_JSON.read_text(encoding="utf-8")))
    yaml_doc = _compile(load_swd_yaml(EXAMPLE_YAML.read_text(encoding="utf-8")))
    text_doc = compile_swd_text(
        EXAMPLE_YAML.read_text(encoding="utf-8"),
        handlers=EXAMPLE_HANDLERS,
        providers=EXAMPLE_PROVIDERS,
    )
    assert json_doc.sha256 == yaml_doc.sha256
    assert yaml_doc.sha256 == text_doc.sha256
    assert json_doc.entrypoint == "investigate"
    assert len(json_doc.sha256) == 64


def test_unknown_node_type_is_rejected() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["nodes"]["search_contracts"]["type"] = "magic"
    with pytest.raises(SwdValidationError, match="unknown node type"):
        _compile(document)


def test_unknown_handler_is_rejected() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    with pytest.raises(SwdValidationError, match="unknown handler"):
        compile_definition(
            document,
            handlers=frozenset({"research.other"}),
            providers=EXAMPLE_PROVIDERS,
        )


def test_string_condition_is_rejected() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["nodes"]["check_budget"]["condition"] = "3 < 5"
    with pytest.raises(SwdValidationError):
        _compile(document)


def test_unreachable_node_is_rejected() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["nodes"]["orphan"] = {
        "type": "end",
        "status": "failed",
    }
    with pytest.raises(SwdValidationError, match="unreachable nodes"):
        _compile(document)


def test_non_terminal_loop_is_rejected() -> None:
    document = {
        "version": "1.0",
        "name": "loop_forever",
        "entrypoint": "choose",
        "limits": {"max_steps": 10, "max_depth": 2, "timeout_seconds": 30},
        "nodes": {
            "choose": {
                "type": "decision",
                "evaluator": "expression",
                "condition": {"const": True},
                "routes": {"true": "ping", "false": "done"},
            },
            "ping": {"type": "task", "handler": "research.execute_need", "next": "pong"},
            "pong": {"type": "task", "handler": "research.execute_need", "next": "ping"},
            "done": {"type": "end", "status": "completed"},
        },
    }
    with pytest.raises(SwdValidationError, match="never reach end"):
        _compile(document)


def test_join_requires_owning_fork() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["nodes"]["stray_join"] = {
        "type": "join",
        "mode": "all",
        "next": "end_complete",
    }
    with pytest.raises(SwdValidationError, match="exactly one fork or map"):
        _compile(document)


def test_map_definition_compiles() -> None:
    document = {
        "version": "1.0",
        "name": "map_needs",
        "entrypoint": "fanout",
        "limits": {"max_steps": 50, "max_depth": 4, "timeout_seconds": 60},
        "nodes": {
            "fanout": {
                "type": "map",
                "items": "$.needs",
                "child": "run_need",
                "concurrency": 8,
                "join": "after_needs",
            },
            "run_need": {"type": "task", "handler": "research.execute_need"},
            "after_needs": {"type": "join", "mode": "all", "next": "done"},
            "done": {"type": "end", "status": "completed"},
        },
    }
    compiled = _compile(document)
    assert compiled.entrypoint == "fanout"


def test_unsupported_version_is_rejected() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["version"] = "2.0"
    with pytest.raises(SwdValidationError, match="unsupported SWD version"):
        _compile(document)


def test_example_document_is_not_mutated() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    original = copy.deepcopy(document)
    _compile(document)
    assert document == original


def test_compiled_document_is_immutable() -> None:
    compiled = _compile(json.loads(EXAMPLE_JSON.read_text(encoding="utf-8")))
    with pytest.raises(TypeError):
        compiled.document["name"] = "mutated"  # type: ignore[index]
    nodes = compiled.document["nodes"]
    with pytest.raises(TypeError):
        nodes["investigate"] = {}
    investigate = nodes["investigate"]
    with pytest.raises(TypeError):
        investigate["type"] = "task"
    choices = nodes["evaluate"]["choices"]
    with pytest.raises(TypeError):
        choices[0] = "mutated"  # type: ignore[index]


def test_compiled_document_matches_canonical_hash() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["nodes"]["search_contracts"]["input"] = {
        "label": {"const": "e\u0301"},
        "count": {"const": 1.0},
    }
    compiled = _compile(document)
    payload = compiled.document["nodes"]["search_contracts"]["input"]
    assert payload["label"]["const"] == "é"
    assert payload["count"]["const"] == 1
    assert compiled.sha256 == sha256_hex(compiled.document)


def test_example_uses_catalog_prompt_key() -> None:
    compiled = _compile(json.loads(EXAMPLE_JSON.read_text(encoding="utf-8")))
    evaluate = compiled.document["nodes"]["evaluate"]
    assert evaluate["prompt_key"] == EXAMPLE_PROMPT_KEY
    assert "question" not in evaluate


def test_inline_provider_question_is_rejected() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    evaluate = document["nodes"]["evaluate"]
    evaluate.pop("prompt_key")
    evaluate["question"] = "hardcoded question"
    with pytest.raises(SwdValidationError):
        _compile(document)


def test_unknown_prompt_key_is_rejected() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["nodes"]["evaluate"]["prompt_key"] = "research.not_a_catalog_key"
    with pytest.raises(SwdValidationError, match="unknown prompt_key"):
        _compile(document)


def test_expression_routes_must_be_exactly_true_false() -> None:
    document = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    document["nodes"]["check_budget"]["routes"]["maybe"] = "evaluate"
    with pytest.raises(SwdValidationError, match="exactly true and false|not valid under any"):
        _compile(document)
