"""Bounded concurrency slots for research needs, sources, and documents.

Need retrieval already uses a per-wave semaphore from
``research_need_concurrency``. Source and document slots exist so later
phases can overlap those loops; both default to 1 so current callers stay
serial until those loops change.

``research_concurrency()`` keeps one limiter set for the current event
loop. ``asyncio.Semaphore`` is loop-bound, so a later call on a different
running loop (pytest creates one loop per test) gets a fresh set. That
still caps in-flight document work inside one process and one loop.
Source candidates use a fresh per-need semaphore so the default of 1
does not serialize every concurrent need. Candidates that expose the
same ``shared_db_session`` still run one at a time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass

from app.config import settings


def require_concurrency_limit(value: int, name: str) -> int:
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


@dataclass(frozen=True)
class ResearchConcurrencyLimits:
    needs: int
    sources: int
    documents: int

    def __post_init__(self) -> None:
        require_concurrency_limit(self.needs, "research_need_concurrency")
        require_concurrency_limit(self.sources, "research_source_concurrency")
        require_concurrency_limit(self.documents, "research_document_concurrency")

    @classmethod
    def from_settings(cls) -> ResearchConcurrencyLimits:
        return cls(
            needs=settings.research_need_concurrency,
            sources=settings.research_source_concurrency,
            documents=settings.research_document_concurrency,
        )


class ResearchConcurrency:
    """One semaphore set for need / source / document work."""

    def __init__(
        self,
        limits: ResearchConcurrencyLimits,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.limits = limits
        self.loop = loop
        self.needs = asyncio.Semaphore(limits.needs)
        self.sources = asyncio.Semaphore(limits.sources)
        self.documents = asyncio.Semaphore(limits.documents)


async def map_with_limit[T, R](
    slots: asyncio.Semaphore,
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R]],
) -> list[R]:
    """Run ``worker`` over ``items`` with at most ``slots`` in flight.

    Result order matches ``items``. Source candidates and document fetches
    use this helper.
    """

    async def run(item: T) -> R:
        async with slots:
            return await worker(item)

    return list(await asyncio.gather(*(run(item) for item in items)))


_shared_concurrency: ResearchConcurrency | None = None


def _optional_running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def research_concurrency() -> ResearchConcurrency:
    """One limiter set for the current event loop."""
    global _shared_concurrency
    loop = _optional_running_loop()
    if _shared_concurrency is None or _shared_concurrency.loop is not loop:
        _shared_concurrency = ResearchConcurrency(
            ResearchConcurrencyLimits.from_settings(),
            loop=loop,
        )
    return _shared_concurrency


def source_candidate_slots() -> asyncio.Semaphore:
    """Per-need candidate slots from ``research_source_concurrency``.

    A process-wide source semaphore at the default of 1 would serialize
    every ``source.research()`` and starve ``research_need_concurrency``.
    """
    return asyncio.Semaphore(ResearchConcurrencyLimits.from_settings().sources)


def shared_db_session(source: object | None) -> object | None:
    """Session the adapter already holds, if any. Missing means no sharing."""
    if source is None:
        return None
    return getattr(source, "shared_db_session", None)


def session_guard(
    locks: dict[int, asyncio.Lock],
    session: object | None,
) -> AbstractAsyncContextManager[None]:
    """Serialize candidates that reuse the same ``AsyncSession``."""
    if session is None:
        return nullcontext()
    return locks.setdefault(id(session), asyncio.Lock())


def reset_research_concurrency() -> None:
    """Drop the process-wide limiter set. Tests only."""
    global _shared_concurrency
    _shared_concurrency = None
