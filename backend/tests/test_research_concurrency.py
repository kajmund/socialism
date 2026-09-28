"""Research concurrency limiters bound need, source, and document work."""

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
    shared_db_session,
    source_candidate_slots,
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


def test_research_concurrency_rebinds_when_loop_changes():
    reset_research_concurrency()
    seen: list[ResearchConcurrency] = []

    async def capture() -> None:
        seen.append(research_concurrency())

    asyncio.run(capture())
    asyncio.run(capture())
    assert seen[0] is not seen[1]
    assert seen[0].loop is not seen[1].loop
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_research_concurrency_binds_to_running_loop():
    reset_research_concurrency()
    first = research_concurrency()
    second = research_concurrency()
    assert first is second
    assert first.loop is asyncio.get_running_loop()
    reset_research_concurrency()


def test_source_candidate_slots_are_per_call():
    reset_research_concurrency()
    first = source_candidate_slots()
    second = source_candidate_slots()
    assert first is not second
    assert first is not research_concurrency().sources
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


class _CountingSource:
    def __init__(self, source_type: str, *, session: object | None = None) -> None:
        self.source_type = source_type
        self.provider_id = f"fake.{source_type}"
        self.shared_db_session = session
        self.current = 0
        self.max_seen = 0
        self._lock = asyncio.Lock()
        self._shared: _CountingSource | None = None

    def share_counter_with(self, other: _CountingSource) -> None:
        self._shared = other

    async def research(self, need: ResearchNeed, context: ResearchContext):
        owner = self._shared or self
        async with owner._lock:
            owner.current += 1
            owner.max_seen = max(owner.max_seen, owner.current)
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
            async with owner._lock:
                owner.current -= 1


def _two_source_need() -> tuple[ResearchRouter, _CountingSource]:
    first = _CountingSource("case_knowledge")
    second = _CountingSource("customer_knowledge")
    second.share_counter_with(first)
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(first)
    registry.register(second)
    return ResearchRouter(registry), first


def _need_and_context() -> tuple[ResearchNeed, ResearchContext]:
    return (
        ResearchNeed(
            id="research_1",
            question="Vad gäller skattesatsen?",
            why_needed="behövs för bedömning",
            requested_by=["legal"],
            source_types=["case_knowledge", "customer_knowledge"],
        ),
        ResearchContext(scope=KnowledgeScope(customer_id=7, case_id="case-1", module="dd")),
    )


@pytest.mark.asyncio
async def test_execute_need_stays_serial_by_default():
    reset_research_concurrency()
    router, counter = _two_source_need()
    need, context = _need_and_context()
    evidence = await router.execute_need(need, context)
    assert [item.source_type for item in evidence] == [
        "case_knowledge",
        "customer_knowledge",
    ]
    assert counter.max_seen == 1
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_execute_need_overlaps_when_source_limit_is_raised(monkeypatch):
    monkeypatch.setattr(settings, "research_source_concurrency", 2)
    reset_research_concurrency()
    router, counter = _two_source_need()
    need, context = _need_and_context()
    evidence = await router.execute_need(need, context)
    assert [item.source_type for item in evidence] == [
        "case_knowledge",
        "customer_knowledge",
    ]
    assert counter.max_seen == 2
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_concurrent_needs_overlap_at_default_source_limit():
    reset_research_concurrency()
    first = _CountingSource("case_knowledge")
    second = _CountingSource("customer_knowledge")
    second.share_counter_with(first)
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(first)
    registry.register(second)
    router = ResearchRouter(registry)
    context = ResearchContext(scope=KnowledgeScope(customer_id=7, case_id="case-1", module="dd"))
    await asyncio.gather(
        router.execute_need(
            ResearchNeed(
                id="research_1",
                question="Vad gäller skattesatsen?",
                why_needed="behövs för bedömning",
                requested_by=["legal"],
                source_types=["case_knowledge"],
            ),
            context,
        ),
        router.execute_need(
            ResearchNeed(
                id="research_2",
                question="Vad gäller kunden?",
                why_needed="behövs för bedömning",
                requested_by=["legal"],
                source_types=["customer_knowledge"],
            ),
            context,
        ),
    )
    assert first.max_seen == 2
    reset_research_concurrency()


def test_shared_db_session_reads_optional_attribute():
    assert shared_db_session(None) is None
    assert shared_db_session(object()) is None
    holder = _CountingSource("case_knowledge", session="db")
    assert shared_db_session(holder) == "db"


@pytest.mark.asyncio
async def test_shared_session_candidates_stay_serial_when_limit_is_raised(monkeypatch):
    monkeypatch.setattr(settings, "research_source_concurrency", 2)
    reset_research_concurrency()
    session = object()
    first = _CountingSource("case_knowledge", session=session)
    second = _CountingSource("customer_knowledge", session=session)
    second.share_counter_with(first)
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(first)
    registry.register(second)
    router = ResearchRouter(registry)
    need, context = _need_and_context()
    evidence = await router.execute_need(need, context)
    assert [item.source_type for item in evidence] == [
        "case_knowledge",
        "customer_knowledge",
    ]
    assert first.max_seen == 1
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_distinct_session_candidates_overlap_when_limit_is_raised(monkeypatch):
    monkeypatch.setattr(settings, "research_source_concurrency", 2)
    reset_research_concurrency()
    first = _CountingSource("case_knowledge", session=object())
    second = _CountingSource("customer_knowledge", session=object())
    second.share_counter_with(first)
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(first)
    registry.register(second)
    router = ResearchRouter(registry)
    need, context = _need_and_context()
    evidence = await router.execute_need(need, context)
    assert [item.source_type for item in evidence] == [
        "case_knowledge",
        "customer_knowledge",
    ]
    assert first.max_seen == 2
    reset_research_concurrency()
