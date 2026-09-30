"""Bounded follow-up validation with ordered results and owned task lifetimes."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

from app.config import settings
from app.services.research.followup import FollowUpNeedDraft

_timings: ContextVar[dict[str, float] | None] = ContextVar("gap_timings", default=None)


@contextmanager
def record_gap_timings(timings: dict[str, float] | None):
    token = _timings.set(timings)
    try:
        yield
    finally:
        _timings.reset(token)


@contextmanager
def measure_gap_stage(name: str):
    started = perf_counter()
    try:
        yield
    finally:
        timings = _timings.get()
        if timings is not None:
            timings[name] = perf_counter() - started


async def validate_followups(
    drafts: Sequence[FollowUpNeedDraft],
    normalize: Callable[[FollowUpNeedDraft], Awaitable[list[FollowUpNeedDraft]]],
) -> list[FollowUpNeedDraft]:
    semaphore = asyncio.Semaphore(settings.research_need_concurrency)

    async def check(index: int, draft: FollowUpNeedDraft) -> list[FollowUpNeedDraft]:
        async with semaphore:
            with measure_gap_stage(f"legal_validation_{index + 1}"):
                return await normalize(draft)

    with measure_gap_stage("legal_validation"):
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(check(i, draft)) for i, draft in enumerate(drafts)]
    return [draft for task in tasks for draft in task.result()]
