"""asyncio handler dispatch. Never wait on handlers while holding the Rust lock."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.swe.runtime_errors import SweHandlerError
from app.swe.runtime_validate import require_json_value, validate_output_schema

Handler = Callable[[Mapping[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class HandlerOutcome:
    invocation_id: str
    node_id: str
    ok: bool
    value: Any
    cancelled: bool = False


def spawn_invocations(
    effects: list[Mapping[str, Any]],
    *,
    handlers: Mapping[str, Handler],
    nodes: Mapping[str, Any],
    pending: dict[str, asyncio.Task[HandlerOutcome]],
    semaphore: asyncio.Semaphore,
) -> None:
    for effect in effects:
        if effect["type"] != "invoke_handler":
            continue
        invocation_id = effect["invocation_id"]
        pending[invocation_id] = asyncio.create_task(
            _run_handler(effect, handlers, nodes, semaphore),
            name=f"swe:{invocation_id}",
        )


def cancel_invocations(
    effects: list[Mapping[str, Any]],
    pending: dict[str, asyncio.Task[HandlerOutcome]],
) -> None:
    for effect in effects:
        if effect["type"] != "cancel_invocation":
            continue
        task = pending.pop(effect["invocation_id"], None)
        if task is not None:
            task.cancel()


def cancel_all(pending: dict[str, asyncio.Task[HandlerOutcome]]) -> None:
    for task in pending.values():
        task.cancel()
    pending.clear()


async def _run_handler(
    effect: Mapping[str, Any],
    handlers: Mapping[str, Handler],
    nodes: Mapping[str, Any],
    semaphore: asyncio.Semaphore,
) -> HandlerOutcome:
    invocation_id = effect["invocation_id"]
    node_id = effect["node_id"]
    try:
        async with semaphore:
            output = await handlers[effect["handler"]](effect["input"])
        output = require_json_value(output, node_id=node_id)
        validate_output_schema(nodes[node_id], output, node_id=node_id)
        return HandlerOutcome(invocation_id, node_id, True, output)
    except asyncio.CancelledError:
        return HandlerOutcome(invocation_id, node_id, False, None, cancelled=True)
    except SweHandlerError as exc:
        return HandlerOutcome(invocation_id, node_id, False, str(exc))
