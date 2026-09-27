"""Graph revalidation is queued after commit and does not block retrieval."""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import GraphRevalidationWork, Kund
from app.jev.service import background_jev_slots
from app.services.knowledge.revalidation_work import (
    FAILED,
    PENDING,
    SUCCEEDED,
    enqueue_graph_revalidation,
    reset_graph_revalidation_worker,
    revalidation_idempotency_key,
    run_due_graph_revalidations,
    schedule_graph_revalidation,
    set_graph_revalidation_performer,
    set_graph_revalidation_scheduling,
    set_graph_revalidation_session_factory,
    wait_graph_revalidation_workers,
)


@pytest.fixture
async def factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_graph_revalidation_session_factory(session_factory)
    try:
        yield session_factory
    finally:
        await wait_graph_revalidation_workers()
        reset_graph_revalidation_worker()
        await engine.dispose()


async def _customer(session: AsyncSession, slug: str) -> Kund:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    return kund


def test_background_graph_work_leaves_a_foreground_jev_slot():
    slots = background_jev_slots()
    if settings.jev_max_concurrency > 1:
        assert slots < settings.jev_max_concurrency
        assert slots <= settings.graph_revalidation_max_concurrency
    else:
        assert slots == settings.jev_max_concurrency


async def test_same_document_state_is_one_work_row(factory):
    async with factory() as session:
        kund = await _customer(session, "acme")
        first = await enqueue_graph_revalidation(
            session,
            customer_id=kund.id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=["e1"],
        )
        second = await enqueue_graph_revalidation(
            session,
            customer_id=kund.id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=["e1"],
        )
        await session.commit()
    assert first is not None and second is not None
    assert first.id == second.id


async def test_new_document_version_is_new_work(factory):
    async with factory() as session:
        kund = await _customer(session, "acme-version")
        first = await enqueue_graph_revalidation(
            session,
            customer_id=kund.id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=[],
        )
        second = await enqueue_graph_revalidation(
            session,
            customer_id=kund.id,
            document_id="doc",
            document_version_id="v2",
            claim_ids=["c1"],
            relationship_ids=[],
        )
        await session.commit()
    assert first is not None and second is not None
    assert first.id != second.id
    assert revalidation_idempotency_key(
        customer_id=kund.id,
        document_version_id="v1",
        claim_ids=["c1"],
        relationship_ids=[],
    ) != revalidation_idempotency_key(
        customer_id=kund.id,
        document_version_id="v2",
        claim_ids=["c1"],
        relationship_ids=[],
    )


async def test_tenants_do_not_share_a_work_row(factory):
    async with factory() as session:
        first_customer = await _customer(session, "acme-a")
        second_customer = await _customer(session, "acme-b")
        first = await enqueue_graph_revalidation(
            session,
            customer_id=first_customer.id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=[],
        )
        second = await enqueue_graph_revalidation(
            session,
            customer_id=second_customer.id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=[],
        )
        await session.commit()
    assert first is not None and second is not None
    assert first.id != second.id
    assert first.customer_id != second.customer_id


async def test_foreground_continues_while_graph_work_is_blocked(factory):
    release = asyncio.Event()
    entered = asyncio.Event()

    async def blocked(session: AsyncSession, work: GraphRevalidationWork) -> None:
        del work
        await session.commit()
        entered.set()
        await release.wait()

    set_graph_revalidation_performer(blocked)
    set_graph_revalidation_scheduling(True)
    try:
        async with factory() as session:
            kund = await _customer(session, "acme-block")
            started = time.perf_counter()
            first = await enqueue_graph_revalidation(
                session,
                customer_id=kund.id,
                document_id="doc-1",
                document_version_id="v1",
                claim_ids=["c1"],
                relationship_ids=[],
            )
            await session.commit()
            assert first is not None
            schedule_graph_revalidation(first.id)
            assert time.perf_counter() - started < 0.5
            await asyncio.wait_for(entered.wait(), timeout=1)
            next_started = time.perf_counter()
            second = await enqueue_graph_revalidation(
                session,
                customer_id=kund.id,
                document_id="doc-2",
                document_version_id="v2",
                claim_ids=["c2"],
                relationship_ids=[],
            )
            await session.commit()
            assert second is not None
            schedule_graph_revalidation(second.id)
            assert time.perf_counter() - next_started < 0.5
            assert second.id != first.id
    finally:
        release.set()
        await wait_graph_revalidation_workers()


async def test_graph_failure_retries_without_removing_the_customer_row(factory):
    async def explode(session: AsyncSession, work: GraphRevalidationWork) -> None:
        del session, work
        raise RuntimeError("graph down")

    set_graph_revalidation_performer(explode)
    set_graph_revalidation_scheduling(True)
    async with factory() as session:
        kund = await _customer(session, "acme-fail")
        customer_id = kund.id
        work = await enqueue_graph_revalidation(
            session,
            customer_id=customer_id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=[],
        )
        await session.commit()
        assert work is not None
        work_id = work.id
        schedule_graph_revalidation(work_id)
    await wait_graph_revalidation_workers()
    async with factory() as session:
        row = await session.get(GraphRevalidationWork, work_id)
        assert row is not None
        assert row.status == PENDING
        assert row.attempts == 1
        assert row.error == "graph down"
        assert await session.get(Kund, customer_id) is not None


async def test_exhausted_attempts_stay_failed(factory):
    previous = settings.graph_revalidation_max_attempts
    settings.graph_revalidation_max_attempts = 1

    async def explode(session: AsyncSession, work: GraphRevalidationWork) -> None:
        del session, work
        raise RuntimeError("graph down")

    set_graph_revalidation_performer(explode)
    set_graph_revalidation_scheduling(True)
    try:
        async with factory() as session:
            kund = await _customer(session, "acme-exhausted")
            work = await enqueue_graph_revalidation(
                session,
                customer_id=kund.id,
                document_id="doc",
                document_version_id="v1",
                claim_ids=["c1"],
                relationship_ids=[],
            )
            await session.commit()
            assert work is not None
            work_id = work.id
            schedule_graph_revalidation(work_id)
        await wait_graph_revalidation_workers()
        async with factory() as session:
            row = await session.get(GraphRevalidationWork, work_id)
            assert row is not None
            assert row.status == FAILED
            assert row.attempts == 1
    finally:
        settings.graph_revalidation_max_attempts = previous


async def test_second_trigger_does_not_evaluate_twice(factory):
    calls = 0

    async def count(session: AsyncSession, work: GraphRevalidationWork) -> None:
        del session, work
        nonlocal calls
        calls += 1

    set_graph_revalidation_performer(count)
    set_graph_revalidation_scheduling(True)
    async with factory() as session:
        kund = await _customer(session, "acme-once")
        customer_id = kund.id
        first = await enqueue_graph_revalidation(
            session,
            customer_id=customer_id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=["e1"],
        )
        await session.commit()
        assert first is not None
        schedule_graph_revalidation(first.id)
    await wait_graph_revalidation_workers()
    async with factory() as session:
        again = await enqueue_graph_revalidation(
            session,
            customer_id=customer_id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=["e1"],
        )
        await session.commit()
        assert again is not None
        assert again.status == SUCCEEDED
        schedule_graph_revalidation(again.id)
    await wait_graph_revalidation_workers()
    assert calls == 1


async def test_pending_work_is_reclaimed_after_restart(factory):
    calls = 0

    async def count(session: AsyncSession, work: GraphRevalidationWork) -> None:
        del session, work
        nonlocal calls
        calls += 1

    set_graph_revalidation_performer(count)
    async with factory() as session:
        kund = await _customer(session, "acme-restart")
        work = await enqueue_graph_revalidation(
            session,
            customer_id=kund.id,
            document_id="doc",
            document_version_id="v1",
            claim_ids=["c1"],
            relationship_ids=[],
        )
        await session.commit()
        assert work is not None
        assert work.status == PENDING
    assert calls == 0
    set_graph_revalidation_scheduling(True)
    scheduled = await run_due_graph_revalidations()
    assert scheduled == 1
    await wait_graph_revalidation_workers()
    assert calls == 1
