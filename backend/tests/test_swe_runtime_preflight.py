"""Unsupported SWD features fail closed before a run starts."""

from __future__ import annotations

import pytest

pytest.importorskip("swe_native")

from app.swe.definition import compile_definition
from app.swe.runtime import run_workflow
from app.swe.runtime_errors import SweUnsupportedError
from app.swe.yaml_load import load_swd_json
from tests.swe.helpers import EXAMPLE_HANDLERS, EXAMPLE_PROVIDERS, FIXTURES
from tests.swe.runtime_helpers import compile_runtime

pytestmark = pytest.mark.swe_runtime


async def test_research_fixture_provider_is_unsupported() -> None:
    compiled = compile_definition(
        load_swd_json((FIXTURES / "research_parallel.json").read_text(encoding="utf-8")),
        handlers=EXAMPLE_HANDLERS,
        providers=EXAMPLE_PROVIDERS,
    )
    with pytest.raises(SweUnsupportedError, match="provider"):
        await run_workflow(compiled, {}, {})


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
