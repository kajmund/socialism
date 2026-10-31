"""SWE phase 3: OverGraph run store, atomic transitions and crash-durable resume."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("swe_native")

from app.services.swe_host import WorkflowHostContext
from app.swe.run_store import InvocationRecord, RunRecord
from app.swe.runtime import WorkflowRunner, resume_run, run_workflow
from app.swe.runtime_clock import FrozenClock
from app.swe.runtime_errors import SweRuntimeError
from app.services.overgraph.workflows import (
    EVENT_LABEL,
    INVOCATION_LABEL,
    RUN_LABEL,
    WorkflowRunStore,
)
from tests.swe.runtime_helpers import compile_runtime

pytestmark = pytest.mark.swe_runtime

RESEARCH = WorkflowHostContext(customer_id="1", feature_id="research")
CHAIN_OUTPUT = {"first": {"result": {"n": 2}}, "second": {"result": {"n": 4}}}


class _Crash(Exception):
    """Simulated process death from inside a transition write."""


class _CrashingStore:
    """Wraps a store and raises after ``crash_after`` persisted transitions."""

    def __init__(self, inner: WorkflowRunStore, *, crash_after: int) -> None:
        self.inner = inner
        self.crash_after = crash_after
        self.calls = 0

    async def record(
        self,
        run: RunRecord,
        *,
        events: Any = (),
        invocation: InvocationRecord | None = None,
    ) -> None:
        self.calls += 1
        if self.calls > self.crash_after:
            raise _Crash()
        await self.inner.record(run, events=events, invocation=invocation)

    async def load_run(self, run_id: str) -> RunRecord | None:
        return await self.inner.load_run(run_id)

    async def replay_results(self, run_id: str) -> Mapping[str, InvocationRecord]:
        return await self.inner.replay_results(run_id)

    async def events(self, run_id: str) -> list[dict[str, Any]]:
        return await self.inner.events(run_id)


def _chain() -> Any:
    return compile_runtime(
        {
            "first": {
                "type": "task",
                "handler": "demo.first",
                "input": {"n": "$.n"},
                "next": "second",
            },
            "second": {
                "type": "task",
                "handler": "demo.second",
                "input": {"n": "$.first.result.n"},
                "next": "done",
            },
            "done": {"type": "end", "status": "completed"},
        },
        name="chain",
        entrypoint="first",
        handlers=frozenset({"demo.first", "demo.second"}),
    )


def _one_task(handler: str, *, timeout_seconds: int = 30) -> Any:
    return compile_runtime(
        {
            "work": {"type": "task", "handler": handler, "next": "done"},
            "done": {"type": "end", "status": "completed"},
        },
        name="one",
        entrypoint="work",
        limits={"max_steps": 20, "max_depth": 4, "timeout_seconds": timeout_seconds},
        handlers=frozenset({handler}),
    )


def _handlers(calls: list[str] | None = None) -> dict[str, Any]:
    log = calls if calls is not None else []

    async def first(payload: Mapping[str, Any]) -> dict[str, int]:
        log.append("first")
        return {"n": int(payload["n"]) + 1}

    async def second(payload: Mapping[str, Any]) -> dict[str, int]:
        log.append("second")
        return {"n": int(payload["n"]) * 2}

    return {"demo.first": first, "demo.second": second}


def _open(root: Path, context: WorkflowHostContext = RESEARCH) -> WorkflowRunStore:
    return WorkflowRunStore.open(root, context)


async def test_transitions_events_and_run_record_are_persisted(tmp_path: Path) -> None:
    compiled = _chain()
    store = _open(tmp_path)
    try:
        result = await WorkflowRunner(compiled, _handlers(), run_store=store).run(
            {"n": 1}, run_id="run-1",
        )
        stored = await store.load_run("run-1")
        events = await store.events("run-1")
        replay = await store.replay_results("run-1")
        counts = (
            store.catalog.count_nodes([RUN_LABEL]),
            store.catalog.count_nodes([EVENT_LABEL]),
            store.catalog.count_nodes([INVOCATION_LABEL]),
        )
    finally:
        store.close()

    assert result.status == "completed"
    assert result.output == CHAIN_OUTPUT
    assert stored is not None
    assert stored.status == "completed"
    assert stored.output == CHAIN_OUTPUT
    assert stored.definition_sha256 == compiled.sha256
    assert stored.finished_at_ms is not None
    assert stored.last_seq == len(result.events)
    assert events == result.events
    assert counts == (1, len(result.events), 2)
    assert {record.ok for record in replay.values()} == {True}
    assert sorted(str(record.value) for record in replay.values()) == [
        "{'n': 2}", "{'n': 4}",
    ]


async def test_failed_handler_is_persisted_as_failed_invocation(tmp_path: Path) -> None:
    async def boom(_payload: Mapping[str, Any]) -> dict[str, bool]:
        raise RuntimeError("kaboom")

    store = _open(tmp_path)
    try:
        result = await WorkflowRunner(
            _one_task("demo.boom"), {"demo.boom": boom}, run_store=store,
        ).run({}, run_id="run-boom")
        stored = await store.load_run("run-boom")
        replay = await store.replay_results("run-boom")
    finally:
        store.close()

    assert result.status == "failed"
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == result.error
    assert stored.error is not None and "kaboom" in stored.error["message"]
    assert stored.finished_at_ms is not None
    [invocation] = replay.values()
    assert invocation.ok is False
    assert invocation.error is not None and "kaboom" in invocation.error


async def test_replaying_a_transition_is_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        result = await WorkflowRunner(_chain(), _handlers(), run_store=store).run(
            {"n": 1}, run_id="run-idem",
        )
        stored = await store.load_run("run-idem")
        events = await store.events("run-idem")
        assert stored is not None
        await store.record(stored, events=events)
        after_events = await store.events("run-idem")
        after_run = await store.load_run("run-idem")
    finally:
        store.close()

    assert result.status == "completed"
    assert after_events == events
    assert after_run == stored


async def test_failed_transaction_writes_nothing(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises((TypeError, ValueError)):
            store.catalog.write([
                {"labels": [RUN_LABEL], "key": "run-x", "props": {"run_id": "run-x"}},
                {"labels": [EVENT_LABEL], "key": "run-x:1", "props": {"bad": object()}},
            ])
        assert await store.load_run("run-x") is None
        assert store.catalog.count_nodes([RUN_LABEL]) == 0
        assert store.catalog.count_nodes([EVENT_LABEL]) == 0
    finally:
        store.close()


async def test_resume_after_crash_matches_the_uninterrupted_run(tmp_path: Path) -> None:
    compiled = _chain()
    baseline_calls: list[str] = []
    baseline = _open(tmp_path / "baseline")
    try:
        uninterrupted = await WorkflowRunner(
            compiled, _handlers(baseline_calls), run_store=baseline,
        ).run({"n": 1}, run_id="run-crash")
    finally:
        baseline.close()

    calls: list[str] = []
    store = _open(tmp_path / "crash")
    try:
        with pytest.raises(_Crash):
            await WorkflowRunner(
                compiled, _handlers(calls), run_store=_CrashingStore(store, crash_after=2),
            ).run({"n": 1}, run_id="run-crash")
    finally:
        store.close()

    reopened = _open(tmp_path / "crash")
    try:
        resumed = await WorkflowRunner(
            compiled, _handlers(calls), run_store=reopened,
        ).resume("run-crash")
        stored = await reopened.load_run("run-crash")
        events = await reopened.events("run-crash")
    finally:
        reopened.close()

    assert uninterrupted.status == "completed"
    assert resumed.status == "completed"
    assert resumed.output == CHAIN_OUTPUT
    assert stored is not None and stored.status == "completed"
    assert events == resumed.events == uninterrupted.events
    assert baseline_calls == ["first", "second"]
    assert calls.count("first") == 1
    assert calls.count("second") == 2


async def test_resume_terminal_run_returns_persisted_result(tmp_path: Path) -> None:
    calls: list[str] = []
    store = _open(tmp_path)
    try:
        first = await WorkflowRunner(_chain(), _handlers(calls), run_store=store).run(
            {"n": 1}, run_id="run-done",
        )
    finally:
        store.close()

    reopened = _open(tmp_path)
    try:
        second = await resume_run(
            _chain(), _handlers(calls), run_store=reopened, run_id="run-done",
        )
    finally:
        reopened.close()

    assert first.status == second.status == "completed"
    assert first.output == second.output
    assert calls == ["first", "second"]


async def test_resume_rejects_another_definition(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        await WorkflowRunner(_chain(), _handlers(), run_store=store).run(
            {"n": 1}, run_id="run-sha",
        )
    finally:
        store.close()

    reopened = _open(tmp_path)
    try:
        with pytest.raises(SweRuntimeError, match="another definition"):
            await WorkflowRunner(
                _one_task("demo.first"), _handlers(), run_store=reopened,
            ).resume("run-sha")
    finally:
        reopened.close()


async def test_catalogs_are_isolated_per_customer_and_feature(tmp_path: Path) -> None:
    first = _open(tmp_path)
    other_customer = _open(tmp_path, WorkflowHostContext(customer_id="2", feature_id="research"))
    other_feature = _open(tmp_path, WorkflowHostContext(customer_id="1", feature_id="expert_routing"))
    try:
        await WorkflowRunner(_chain(), _handlers(), run_store=first).run(
            {"n": 1}, run_id="run-iso",
        )
        assert await other_customer.load_run("run-iso") is None
        assert await other_feature.load_run("run-iso") is None
        paths = {first.catalog.path, other_customer.catalog.path, other_feature.catalog.path}
        assert len(paths) == 3
    finally:
        first.close()
        other_customer.close()
        other_feature.close()


async def test_timeout_fails_the_run_and_is_persisted(tmp_path: Path) -> None:
    async def hang(_payload: Mapping[str, Any]) -> dict[str, bool]:
        await asyncio.Event().wait()
        return {"ok": True}

    store = _open(tmp_path)
    try:
        result = await asyncio.wait_for(
            WorkflowRunner(
                _one_task("demo.hang", timeout_seconds=1), {"demo.hang": hang},
                run_store=store,
            ).run({}, run_id="run-timeout"),
            timeout=5,
        )
        stored = await store.load_run("run-timeout")
        events = await store.events("run-timeout")
    finally:
        store.close()

    assert result.status == "failed"
    assert stored is not None and stored.status == "failed"
    assert stored.error is not None and "timeout" in stored.error["message"]
    assert any(event["type"] == "RunFailed" for event in events)


async def test_resume_keeps_the_persisted_start_time(tmp_path: Path) -> None:
    compiled = _one_task("demo.first", timeout_seconds=10)
    store = _open(tmp_path)
    try:
        with pytest.raises(_Crash):
            await WorkflowRunner(
                compiled, _handlers(), run_store=_CrashingStore(store, crash_after=1),
                clock=FrozenClock(),
            ).run({"n": 1}, run_id="run-deadline")
    finally:
        store.close()

    reopened = _open(tmp_path)
    try:
        stored = await reopened.load_run("run-deadline")
        assert stored is not None and stored.started_at_ms == 0
        result = await WorkflowRunner(
            compiled, _handlers(), run_store=reopened, clock=FrozenClock(now=10_000),
        ).resume("run-deadline")
        after = await reopened.load_run("run-deadline")
    finally:
        reopened.close()

    assert result.status == "failed"
    assert after is not None and after.error is not None
    assert "timeout" in after.error["message"]


async def test_run_workflow_without_store_is_unchanged() -> None:
    result = await run_workflow(_chain(), _handlers(), {"n": 1}, run_id="run-plain")
    assert result.status == "completed"
    assert result.output == CHAIN_OUTPUT
