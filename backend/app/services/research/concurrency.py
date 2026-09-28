"""Bounded concurrency slots for research needs, sources, and documents.

Need retrieval already uses a per-wave semaphore from
``research_need_concurrency``. Source and document slots exist so later
phases can overlap those loops; both default to 1 so current callers stay
serial until those loops change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
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

    def __init__(self, limits: ResearchConcurrencyLimits) -> None:
        self.limits = limits
        self.needs = asyncio.Semaphore(limits.needs)
        self.sources = asyncio.Semaphore(limits.sources)
        self.documents = asyncio.Semaphore(limits.documents)


async def map_with_limit[T, R](
    slots: asyncio.Semaphore,
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R]],
) -> list[R]:
    """Run ``worker`` over ``items`` with at most ``slots`` in flight.

    Result order matches ``items``. Current router and document loops stay
    sequential; later phases call this helper to overlap those steps.
    """

    async def run(item: T) -> R:
        async with slots:
            return await worker(item)

    return list(await asyncio.gather(*(run(item) for item in items)))
