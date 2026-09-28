"""Parallel relevance judge() fan-out. Does not retrieve or persist."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.config import settings
from app.services.research.models import ResearchNeed


class RelevanceJudgeError(Exception):
    """Assessor raised an unexpected error. quality.py maps this to EvidenceQualityError."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"Relevance assessor failed for item {item_id}")
        self.item_id = item_id


class _QualityItem(Protocol):
    item_id: str
    status: str
    research_need_id: str | None


class _RelevanceAssessor(Protocol):
    async def judge(self, need: ResearchNeed, item: _QualityItem) -> object: ...


async def judge_found_items(
    items: Sequence[_QualityItem],
    needs_by_id: Mapping[str, ResearchNeed],
    assessor: _RelevanceAssessor,
) -> dict[str, object]:
    jobs: list[tuple[_QualityItem, ResearchNeed]] = []
    for item in items:
        if item.status != "found":
            continue
        need = needs_by_id.get(item.research_need_id or "")
        if need is not None:
            jobs.append((item, need))
    if not jobs:
        return {}
    slots = asyncio.Semaphore(settings.research_relevance_concurrency)

    async def run(item: _QualityItem, need: ResearchNeed) -> tuple[str, object]:
        async with slots:
            try:
                return item.item_id, await assessor.judge(need, item)
            except Exception as exc:
                raise RelevanceJudgeError(item.item_id) from exc

    tasks = [asyncio.create_task(run(item, need)) for item, need in jobs]
    try:
        rows = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return dict(rows)
