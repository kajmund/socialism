"""Thin asyncio adapter around the Rust SWE machine.

Python compiles SWD, owns the event loop, and runs registered async handlers.
Rust owns routing, join barriers, and typed events. The adapter never calls
into Rust while awaiting a handler.

Deadline: the driver waits with the remaining monotonic timeout and calls
`Machine.tick(now_ms)` when it expires. Tick fails the run and emits
`CancelInvocation` for open handlers. Handlers that swallow
`CancelledError` are not force-stopped; terminal status stays protected and
late results do not route again.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.swe.definition import CompiledDefinition
from app.swe.runtime_clock import FrozenClock, WorkflowClock
from app.swe.runtime_dispatch import (
    Handler,
    HandlerOutcome,
    cancel_all,
    cancel_invocations,
    reap_owned,
    spawn_invocations,
)
from app.swe.runtime_errors import SweRuntimeError
from app.swe.runtime_preflight import assert_handlers_registered, assert_phase2_supported
from app.swe.runtime_thaw import thaw_json


@dataclass
class _Driver:
    machine: Any
    handlers: Mapping[str, Handler]
    nodes: Mapping[str, Any]
    clock: WorkflowClock | FrozenClock
    cancel_event: asyncio.Event | None
    pending: dict[str, asyncio.Task[HandlerOutcome]]
    semaphore: asyncio.Semaphore
    cancel_task: asyncio.Task[bool] | None = None


try:
    import swe_native
except ImportError as exc:  # pragma: no cover - exercised by importorskip tests
    swe_native = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    output: Any
    events: list[dict[str, Any]]
    error: dict[str, Any] | None


def require_native() -> Any:
    if swe_native is None:
        raise SweRuntimeError(
            "swe_native is not built; run `make swe-native`",
            kind="preflight",
        ) from _IMPORT_ERROR
    return swe_native


async def run_workflow(
    compiled: CompiledDefinition,
    handlers: Mapping[str, Handler],
    input_data: Mapping[str, Any] | None = None,
    *,
    run_id: str | None = None,
    clock: WorkflowClock | FrozenClock | None = None,
    concurrency: int = 32,
    cancel_event: asyncio.Event | None = None,
) -> RunResult:
    native = require_native()
    document = thaw_json(compiled.document)
    assert_phase2_supported(document)
    assert_handlers_registered(document, handlers)
    machine = native.Machine()
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    clock = clock or WorkflowClock()
    outcome = machine.start(
        document,
        compiled.sha256,
        run_id,
        thaw_json(input_data or {}),
        clock.now_ms(),
    )
    driver = _Driver(
        machine=machine,
        handlers=handlers,
        nodes=document["nodes"],
        clock=clock,
        cancel_event=cancel_event,
        pending={},
        semaphore=asyncio.Semaphore(concurrency),
    )
    try:
        await _drive(driver, outcome)
        return RunResult(
            run_id=run_id,
            status=machine.status(),
            output=machine.output(),
            events=list(machine.events()),
            error=machine.error(),
        )
    finally:
        await reap_owned(driver.pending, driver.cancel_task)
        driver.cancel_task = None


async def _drive(driver: _Driver, outcome: Mapping[str, Any]) -> None:
    _apply_effects(driver, outcome["effects"])
    while driver.machine.status() == "running":
        if _cancelled(driver):
            _apply_effects(driver, driver.machine.cancel(driver.clock.now_ms())["effects"])
            return
        if not driver.pending:
            if _remaining_seconds(driver) <= 0:
                _timeout_run(driver)
            return
        await _apply_one(driver)


def _apply_effects(driver: _Driver, effects: list[Mapping[str, Any]]) -> None:
    spawn_invocations(
        effects,
        handlers=driver.handlers,
        nodes=driver.nodes,
        pending=driver.pending,
        semaphore=driver.semaphore,
    )
    cancel_invocations(effects, driver.pending)


def _cancelled(driver: _Driver) -> bool:
    return driver.cancel_event is not None and driver.cancel_event.is_set()


def _remaining_seconds(driver: _Driver) -> float:
    deadline = driver.machine.deadline_ms()
    now = driver.clock.now_ms()
    if now >= deadline:
        return 0.0
    return (deadline - now) / 1000.0


def _timeout_run(driver: _Driver) -> None:
    now = max(driver.clock.now_ms(), driver.machine.deadline_ms())
    outcome = driver.machine.tick(now)
    _apply_effects(driver, outcome["effects"])


async def _apply_one(driver: _Driver) -> None:
    remaining = _remaining_seconds(driver)
    if remaining <= 0:
        _timeout_run(driver)
        return
    watch = set(driver.pending.values())
    if driver.cancel_event is not None:
        if driver.cancel_task is None or driver.cancel_task.done():
            driver.cancel_task = asyncio.create_task(driver.cancel_event.wait(), name="swe:cancel")
        watch.add(driver.cancel_task)
    finished, _ = await asyncio.wait(
        watch,
        return_when=asyncio.FIRST_COMPLETED,
        timeout=remaining,
    )
    if _cancelled(driver):
        return
    if not finished:
        _timeout_run(driver)
        return
    tasks = [task for task in finished if task.get_name() != "swe:cancel"]
    if not tasks:
        return
    task = tasks[0]
    invocation_id = task.get_name().removeprefix("swe:")
    driver.pending.pop(invocation_id, None)
    if task.cancelled():
        return
    outcome = _report_task(driver, invocation_id, task)
    _apply_effects(driver, outcome["effects"])
    if outcome["status"] != "running":
        cancel_all(driver.pending)


def _report_task(
    driver: _Driver,
    invocation_id: str,
    task: asyncio.Task[HandlerOutcome],
) -> dict[str, Any]:
    error = task.exception()
    if error is not None:
        message = f"{type(error).__name__}: {error}"
        return driver.machine.fail(invocation_id, message, driver.clock.now_ms())
    result = task.result()
    if result.cancelled:
        return {"status": "running", "effects": []}
    if result.ok:
        return driver.machine.complete(result.invocation_id, result.value, driver.clock.now_ms())
    return driver.machine.fail(result.invocation_id, str(result.value), driver.clock.now_ms())


async def identity_handler(_input: Mapping[str, Any]) -> Mapping[str, Any]:
    return dict(_input)


def sync_handler(func: Callable[[Mapping[str, Any]], Any]) -> Handler:
    async def wrapped(payload: Mapping[str, Any]) -> Any:
        return func(payload)

    return wrapped
