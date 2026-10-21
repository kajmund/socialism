"""Cutover wiring: lease-lost, cancellation and the SWE run store seam.

These tests pin the contract between `execute_attempt_research` and the SWE
bridge: the legacy loop seam receives ``lease_lost``, a lost lease ends as
`CancelledError` (never as a failed Attempt), and a persisted SWE run records
the cancelled terminal state when a run store is supplied.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

pytest.importorskip("swe_native")

from app.database.base import Base
from app.services.execution import get_attempt, list_evidence_items, list_need_executions
from app.services.overgraph.workflows import WorkflowRunStore
from app.services.research import swe_bridge
from app.services.research.execution import execute_attempt_research
from app.services.research.models import ResearchPlan
from app.swe.features import WorkflowHostContext
from tests.test_research_assessment import RecordingAssessor
from tests.test_research_execution import RecordingSource, _created_attempt, _need, _router

pytestmark = [
    pytest.mark.swe_runtime,
    pytest.mark.usefixtures("graph_retrieval_embeddings"),
]


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


def _plan() -> ResearchPlan:
    return ResearchPlan(needs=[_need("research_1", "case_knowledge")])


def _edge_router():
    return _router(RecordingSource("case_knowledge"))[0]


async def test_execute_passes_lease_lost_to_the_loop_seam(db) -> None:
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="wiring-kwargs")
    lease_lost = asyncio.Event()
    seen: dict[str, object] = {}

    async def sentinel(**kwargs: object) -> None:
        seen.update(kwargs)

    with mock.patch("app.services.research.execution._run_research_loop", sentinel):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=_plan(),
            router=_edge_router(),
            assessor=RecordingAssessor(),
            lease_lost=lease_lost,
        )

    assert seen.get("lease_lost") is lease_lost
    assert seen.get("start_wave") == 0


async def test_lost_lease_raises_cancelled_error_without_failed_attempt(db) -> None:
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="wiring-cancel")
    lease_lost = asyncio.Event()

    async def cancel_in_bridge(**kwargs: object) -> None:
        lease_lost.set()
        await swe_bridge.run_research_loop_via_swe(**kwargs)

    with mock.patch(
        "app.services.research.execution._run_research_loop", cancel_in_bridge,
    ), pytest.raises(asyncio.CancelledError):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=_plan(),
            router=_edge_router(),
            assessor=RecordingAssessor(),
            lease_lost=lease_lost,
        )

    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.status != "failed"


async def test_cancelled_swe_run_is_persisted_as_cancelled(db, tmp_path) -> None:
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="wiring-store")
    lease_lost = asyncio.Event()
    store = WorkflowRunStore.open(
        tmp_path / "overgraph",
        WorkflowHostContext(customer_id="1", feature_id="research"),
    )
    captured: dict[str, object] = {}

    async def stored_loop(**kwargs: object) -> None:
        loop, plan = swe_bridge.build_loop(kwargs, concurrency=4, run_store=store)
        lease_lost.set()
        result = await loop.run(snapshot_plan=plan, run_id="run-wiring-cancelled")
        captured["status"] = result.status

    try:
        with mock.patch("app.services.research.execution._run_research_loop", stored_loop):
            await execute_attempt_research(
                session,
                attempt_id=attempt.id,
                research_plan=_plan(),
                router=_edge_router(),
                assessor=RecordingAssessor(),
                lease_lost=lease_lost,
            )
        stored = await store.load_run("run-wiring-cancelled")
    finally:
        store.close()

    assert captured.get("status") == "cancelled"
    assert stored is not None
    assert stored.status == "cancelled"


async def test_in_flight_handler_is_cancelled_without_writes(db) -> None:
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="wiring-inflight")
    lease_lost = asyncio.Event()

    class BlockingSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            lease_lost.set()
            await asyncio.Event().wait()

    router, _ = _router(BlockingSource())

    with pytest.raises(asyncio.CancelledError):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=_plan(),
            router=router,
            assessor=RecordingAssessor(),
            lease_lost=lease_lost,
        )

    await session.refresh(attempt)
    assert attempt.status != "failed"
    assert attempt.evidence_set_id is not None
    assert await list_evidence_items(session, attempt.evidence_set_id) == []
    executions = await list_need_executions(session, attempt.id)
    assert all(row.status != "completed" for row in executions)
