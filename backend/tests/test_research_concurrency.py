"""Research concurrency limiters exist without changing serial loops."""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.services.knowledge.models import KnowledgeScope
from app.services.research.concurrency import (
    ResearchConcurrency,
    ResearchConcurrencyLimits,
    map_with_limit,
    require_concurrency_limit,
    research_concurrency,
    reset_research_concurrency,
)
from app.services.research.models import ResearchContext, ResearchNeed, research_evidence
from app.services.research.registry import KnowledgeProviderCapabilityRegistry
from app.services.research.router import ResearchRouter


def test_default_source_and_document_limits_are_serial():
    fields = type(settings).model_fields
    assert fields["research_need_concurrency"].default == 8
    assert fields["research_source_concurrency"].default == 1
    assert fields["research_document_concurrency"].default == 1


def test_limits_follow_settings(monkeypatch):
    monkeypatch.setattr(settings, "research_need_concurrency", 3)
    monkeypatch.setattr(settings, "research_source_concurrency", 2)
    monkeypatch.setattr(settings, "research_document_concurrency", 4)
    limits = ResearchConcurrencyLimits.from_settings()
    assert limits == ResearchConcurrencyLimits(needs=3, sources=2, documents=4)
    bound = ResearchConcurrency(limits)
    assert bound.limits == limits
    assert isinstance(bound.needs, asyncio.Semaphore)
    assert isinstance(bound.sources, asyncio.Semaphore)
    assert isinstance(bound.documents, asyncio.Semaphore)


@pytest.mark.parametrize("name", ["research_source_concurrency", "research_document_concurrency"])
def test_require_concurrency_limit_rejects_zero(name):
    with pytest.raises(ValueError, match=name):
        require_concurrency_limit(0, name)


def test_research_concurrency_is_shared_and_resettable():
    reset_research_concurrency()
    first = research_concurrency()
    second = research_concurrency()
    assert first is second
    assert first.limits == ResearchConcurrencyLimits.from_settings()
    reset_research_concurrency()
    third = research_concurrency()
    assert third is not first
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_map_with_limit_is_serial_at_one():
    current = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def worker(item: int) -> int:
        nonlocal current, max_seen
        async with lock:
            current += 1
            max_seen = max(max_seen, current)
        try:
            await asyncio.sleep(0.02)
            return item * 2
        finally:
            async with lock:
                current -= 1

    result = await map_with_limit(asyncio.Semaphore(1), [1, 2, 3, 4], worker)
    assert result == [2, 4, 6, 8]
    assert max_seen == 1


@pytest.mark.asyncio
async def test_map_with_limit_bounds_overlap_and_keeps_order():
    current = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def worker(item: int) -> int:
        nonlocal current, max_seen
        async with lock:
            current += 1
            max_seen = max(max_seen, current)
        try:
            await asyncio.sleep(0.02)
            return item
        finally:
            async with lock:
                current -= 1

    result = await map_with_limit(asyncio.Semaphore(2), [10, 20, 30, 40], worker)
    assert result == [10, 20, 30, 40]
    assert max_seen == 2


@pytest.mark.asyncio
async def test_execute_need_stays_serial_when_source_limit_is_raised(monkeypatch):
    monkeypatch.setattr(settings, "research_source_concurrency", 8)
    reset_research_concurrency()
    current = 0
    max_seen = 0
    lock = asyncio.Lock()

    class CountingSource:
        def __init__(self, source_type: str) -> None:
            self.source_type = source_type
            self.provider_id = f"fake.{source_type}"

        async def research(self, need: ResearchNeed, context: ResearchContext):
            nonlocal current, max_seen
            async with lock:
                current += 1
                max_seen = max(max_seen, current)
            try:
                await asyncio.sleep(0.03)
                return [
                    research_evidence(
                        research_need_id=need.id,
                        source_type=self.source_type,
                        status="found",
                        excerpt=self.source_type,
                    )
                ]
            finally:
                async with lock:
                    current -= 1

    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(CountingSource("case_knowledge"))
    registry.register(CountingSource("customer_knowledge"))
    evidence = await ResearchRouter(registry).execute_need(
        ResearchNeed(
            id="research_1",
            question="Vad gäller skattesatsen?",
            why_needed="behövs för bedömning",
            requested_by=["legal"],
            source_types=["case_knowledge", "customer_knowledge"],
        ),
        ResearchContext(scope=KnowledgeScope(customer_id=7, case_id="case-1", module="dd")),
    )
    assert [item.source_type for item in evidence] == [
        "case_knowledge",
        "customer_knowledge",
    ]
    assert max_seen == 1
    assert research_concurrency().limits.sources == 8
    reset_research_concurrency()
