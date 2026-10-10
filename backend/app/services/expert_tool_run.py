"""Run one batch of expert tools with a shared factory, timeout, and cancel."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from app.config import settings
from app.services.expert_turn_cancel import current_turn_cancel, turn_is_cancelled
from app.services.live_speech_progress import emit_tool_progress

logger = logging.getLogger(__name__)

RunOne = Callable[[Any, Any], Awaitable[str]]


def tool_failure_text(name: str, kind: str) -> str:
    return f"TOOL_FAILED {name}: verktyget misslyckades ({kind})."


async def execute_tool_calls(work: Any, run_one: RunOne) -> tuple[str, tuple[str, ...]]:
    work.failed_calls = 0
    calls = tuple(work.calls)
    if not calls:
        return "", ()
    remaining = [len(calls)]
    pairs = await asyncio.gather(
        *(
            _one_call(index, call, work, run_one=run_one, remaining=remaining)
            for index, call in enumerate(calls)
        )
    )
    ordered = [text for _index, text in sorted(pairs)]
    parts = [
        f"{call.name}\n{text}"
        for call, text in zip(calls, ordered, strict=True)
        if text
    ]
    return "\n\n".join(parts), tuple(ordered)


async def run_bounded(call: Any, work: Any, run_one: RunOne) -> str:
    """Await one tool until it finishes, the turn is cancelled, or the timeout fires."""
    if turn_is_cancelled():
        raise asyncio.CancelledError
    timeout = settings.expert_tool_timeout_seconds
    cancel = current_turn_cancel()
    runner = asyncio.create_task(run_one(call, work))
    waiters = {runner, asyncio.create_task(asyncio.sleep(timeout))}
    if cancel is not None:
        waiters.add(asyncio.create_task(cancel.wait()))
    try:
        done, _pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        runner.cancel()
        raise
    finally:
        await _stop_waiters(waiters, runner)
    if runner in done:
        return runner.result()
    runner.cancel()
    with suppress(asyncio.CancelledError):
        await runner
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    raise TimeoutError


async def _one_call(
    index: int,
    call: Any,
    work: Any,
    *,
    run_one: RunOne,
    remaining: list[int],
) -> tuple[int, str]:
    await emit_tool_progress("started", call.name, remaining=remaining[0])
    text = await _text_or_failure(call, work, run_one)
    remaining[0] -= 1
    await emit_tool_progress(
        "partial",
        call.name,
        remaining=remaining[0],
        summary=text,
    )
    return index, text


async def _text_or_failure(call: Any, work: Any, run_one: RunOne) -> str:
    try:
        return await run_bounded(call, work, run_one)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        logger.warning("Expert tool %s timed out", call.name)
        work.failed_calls += 1
        return tool_failure_text(call.name, "timeout")
    except Exception:
        logger.exception("Expert tool %s failed", call.name)
        work.failed_calls += 1
        return tool_failure_text(call.name, "error")


async def _stop_waiters(waiters: set[asyncio.Task[Any]], runner: asyncio.Task[str]) -> None:
    for waiter in waiters:
        if waiter is not runner and not waiter.done():
            waiter.cancel()
    for waiter in waiters:
        if waiter is runner:
            continue
        with suppress(asyncio.CancelledError):
            await waiter
