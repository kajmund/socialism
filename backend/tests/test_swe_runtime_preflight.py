"""Reserved SWD features fail closed before a run starts."""

from __future__ import annotations

import pytest

pytest.importorskip("swe_native")

from app.swe.definition import compile_definition
from app.swe.runtime import WorkflowResources, run_workflow
from app.swe.runtime_errors import SwePreflightError, SweUnsupportedError
from app.swe.yaml_load import load_swd_json
from tests.swe.helpers import EXAMPLE_HANDLERS, EXAMPLE_PROVIDERS, FIXTURES
from tests.swe.runtime_helpers import compile_runtime

pytestmark = pytest.mark.swe_runtime

PROVIDER_FIXTURE = {
    "version": "1.0",
    "name": "provider_fixture",
    "entrypoint": "evaluate",
    "limits": {"max_steps": 10, "max_depth": 2, "timeout_seconds": 30},
    "nodes": {
        "evaluate": {
            "type": "decision",
            "evaluator": "provider",
            "provider": "fake",
            "prompt_key": "research.assessment.user",
            "choices": ["yes", "no"],
            "routes": {"yes": "done", "no": "done"},
        },
        "done": {"type": "end", "status": "completed"},
    },
}


async def test_research_fixture_requires_registered_provider() -> None:
    compiled = compile_definition(
        load_swd_json((FIXTURES / "research_parallel.json").read_text(encoding="utf-8")),
        handlers=EXAMPLE_HANDLERS,
        providers=EXAMPLE_PROVIDERS,
    )
    handlers = {name: _ok for name in EXAMPLE_HANDLERS}
    with pytest.raises(SwePreflightError, match="decision provider"):
        await run_workflow(compiled, handlers, {})


async def test_provider_decision_requires_active_prompt() -> None:
    compiled = compile_definition(PROVIDER_FIXTURE, providers=frozenset({"fake"}))
    resources = WorkflowResources(providers={"fake": _provider})
    with pytest.raises(SwePreflightError, match="active prompt"):
        await run_workflow(compiled, {}, {}, resources=resources)


async def test_wait_is_unsupported() -> None:
    compiled = compile_runtime(
        {
            "pause": {"type": "wait", "next": "done"},
            "done": {"type": "end", "status": "completed"},
        },
        name="waiter",
        entrypoint="pause",
    )
    with pytest.raises(SweUnsupportedError, match="wait"):
        await run_workflow(compiled, {}, {})


async def test_subworkflow_is_unsupported() -> None:
    compiled = compile_runtime(
        {
            "child": {"type": "subworkflow", "workflow": "other", "next": "done"},
            "done": {"type": "end", "status": "completed"},
        },
        name="nested",
        entrypoint="child",
    )
    with pytest.raises(SweUnsupportedError, match="subworkflow"):
        await run_workflow(compiled, {}, {})


async def test_exact_cache_and_retry_are_unsupported() -> None:
    cache = compile_runtime(
        {
            "work": {
                "type": "task",
                "handler": "demo.work",
                "cache_policy": "exact",
                "next": "done",
            },
            "done": {"type": "end", "status": "completed"},
        },
        name="cached",
        entrypoint="work",
        handlers=frozenset({"demo.work"}),
    )
    with pytest.raises(SweUnsupportedError, match="cache_policy"):
        await run_workflow(cache, {"demo.work": _ok}, {})

    retry = compile_runtime(
        {
            "work": {
                "type": "task",
                "handler": "demo.work",
                "retry": {"max_attempts": 2},
                "next": "done",
            },
            "done": {"type": "end", "status": "completed"},
        },
        name="retried",
        entrypoint="work",
        handlers=frozenset({"demo.work"}),
    )
    with pytest.raises(SweUnsupportedError, match="retry"):
        await run_workflow(retry, {"demo.work": _ok}, {})


async def _ok(_payload: dict[str, object]) -> dict[str, bool]:
    return {"ok": True}


async def _provider(_request: dict[str, object]) -> str:
    return "yes"
