"""Durable research claims: start, lease, reclaim, no duplicate runs."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionResearchClaim,
    Kund,
    ResearchNeedExecution,
    ResearchRuntimeNeed,
)
from app.services.execution import (
    claim_attempt_researching,
    create_attempt,
    create_evidence_set,
    create_run,
    fail_attempt,
    get_attempt,
    list_need_executions,
    seed_need_executions,
)
from app.services.execution.errors import ExecutionStatusError
from app.services.execution.service import attach_evidence_set, utc_now
from app.services.research.claims import (
    claim_research_lease,
    enqueue_research_claim,
    list_claimable_attempt_ids,
    release_research_lease,
    start_request_payload,
)
from app.services.research.composition import set_research_router_factory
from app.services.research.execution import execute_attempt_research
from app.services.research.models import ResearchContext, ResearchNeed, ResearchPlan
from app.services.research.plan import research_plan_to_snapshot
from app.services.research.planner import FakeResearchPlanner, ResearchNeedDraft
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.router import ResearchRouter
from app.services.research.worker import (
    accept_attempt_research,
    run_due_research_claims,
    run_research_claim,
    set_research_schedule_hook,
    set_research_session_factory,
    wait_research_workers,
)
from app.services.research.models import research_evidence
from tests.test_execution_api import RESEARCH_PLAN, _create_attempt, _create_run
from tests.test_research_execution import RecordingSource, _need, _router


@pytest.fixture
async def worker_db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_research_session_factory(factory)
    set_research_schedule_hook(lambda _attempt_id: None)
    async with factory() as session:
        yield session, factory
    await wait_research_workers()
    set_research_session_factory(None)
    set_research_schedule_hook(None)
    await engine.dispose()


async def _attempt(session: AsyncSession, slug: str) -> tuple[object, object, ExecutionAttempt]:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    run = await create_run(
        session,
        customer_id=kund.id,
        module="dd",
        title="Skattesats",
        context={"case_id": "case-1"},
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    return kund, run, attempt


@pytest.mark.asyncio
async def test_two_workers_cannot_own_the_same_active_lease(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "lease-co")
    await enqueue_research_claim(
        session,
        attempt.id,
        start_request=start_request_payload(
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(
                ResearchPlan(needs=[_need("research_1", "case_knowledge")])
            ),
        ),
    )
    await session.commit()

    async with factory() as first_session, factory() as second_session:
        first = await claim_research_lease(first_session, attempt.id, worker_id="worker-a")
        await first_session.commit()
        second = await claim_research_lease(second_session, attempt.id, worker_id="worker-b")
        await second_session.commit()
    assert first is not None
    assert second is None
    async with factory() as check:
        row = await check.get(ExecutionResearchClaim, attempt.id)
        assert row is not None
        assert row.worker_id == "worker-a"
        assert row.lease_token == first.lease_token


@pytest.mark.asyncio
async def test_expired_lease_can_be_reclaimed(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "expire-co")
    await enqueue_research_claim(
        session,
        attempt.id,
        start_request=start_request_payload(
            research_objective=None,
            research_context={},
            research_plan={"needs": []},
        ),
    )
    first = await claim_research_lease(session, attempt.id, worker_id="dead-worker")
    assert first is not None
    first.lease_expires_at = utc_now() - timedelta(seconds=1)
    await session.commit()

    async with factory() as other:
        assert await list_claimable_attempt_ids(other) == [attempt.id]
        claimed = await claim_research_lease(other, attempt.id, worker_id="live-worker")
        await other.commit()
    assert claimed is not None
    assert claimed.worker_id == "live-worker"
    assert claimed.lease_token != first.lease_token


@pytest.mark.asyncio
async def test_duplicate_start_does_not_duplicate_claim_or_evidence(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "dup-co")
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    payload = start_request_payload(
        research_objective=None,
        research_context={},
        research_plan=research_plan_to_snapshot(plan),
    )
    first = await enqueue_research_claim(session, attempt.id, start_request=payload)
    second = await enqueue_research_claim(session, attempt.id, start_request=payload)
    await session.commit()
    assert first.attempt_id == second.attempt_id == attempt.id

    router, sources = _router(RecordingSource("case_knowledge"))
    set_research_router_factory(lambda _session: router)
    try:
        await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        await run_research_claim(attempt.id)
        await run_research_claim(attempt.id)
    finally:
        set_research_router_factory(None)

    async with factory() as check:
        claims = (await check.execute(select(func.count()).select_from(ExecutionResearchClaim))).scalar()
        sets = (await check.execute(select(func.count()).select_from(EvidenceSet))).scalar()
        items = (await check.execute(select(func.count()).select_from(EvidenceSetItem))).scalar()
        needs = (await check.execute(select(func.count()).select_from(ResearchRuntimeNeed))).scalar()
        executions = (
            await check.execute(select(func.count()).select_from(ResearchNeedExecution))
        ).scalar()
        row = await get_attempt(check, attempt.id)
    assert claims == 1
    assert sets == 1
    assert items == 1
    assert needs == 1
    assert executions == 1
    assert row.status == "ready"
    assert sources[0].calls == 1


@pytest.mark.asyncio
async def test_reclaim_resumes_same_objective_plan_and_evidence_set(worker_db):
    session, factory = worker_db
    _kund, run, attempt = await _attempt(session, "resume-co")
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    await claim_attempt_researching(
        session, attempt.id, research_plan_snapshot=research_plan_to_snapshot(plan)
    )
    evidence_set = await create_evidence_set(
        session, run_id=run.id, created_from_attempt_id=attempt.id
    )
    await attach_evidence_set(
        session, attempt_id=attempt.id, evidence_set_id=evidence_set.id
    )
    await seed_need_executions(session, attempt_id=attempt.id, need_ids=["research_1"])
    await enqueue_research_claim(
        session,
        attempt.id,
        start_request=start_request_payload(
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        ),
    )
    await session.commit()

    planner = FakeResearchPlanner(
        [
            ResearchNeedDraft(
                question="should not run",
                why_needed="x",
                source_types=["case_knowledge"],
            )
        ]
    )
    router, sources = _router(RecordingSource("case_knowledge"))
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        research_planner=planner,
        router=router,
    )
    reloaded = await get_attempt(session, attempt.id)
    executions = await list_need_executions(session, attempt.id)
    assert result.status == "ready"
    assert result.evidence_set_id == evidence_set.id
    assert reloaded.evidence_set_id == evidence_set.id
    assert reloaded.research_plan_snapshot == research_plan_to_snapshot(plan)
    assert {row.status for row in executions} == {"completed"}
    assert sources[0].calls == 1


@pytest.mark.asyncio
async def test_terminal_attempt_is_not_re_run(worker_db):
    session, _factory = worker_db
    _kund, _run, ready = await _attempt(session, "ready-co")
    router, sources = _router(RecordingSource("case_knowledge"))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    await execute_attempt_research(
        session, attempt_id=ready.id, research_plan=plan, router=router
    )
    again = await accept_attempt_research(
        session,
        attempt_id=ready.id,
        research_objective=None,
        research_context={},
        research_plan=research_plan_to_snapshot(plan),
    )
    assert again == "200"
    assert sources[0].calls == 1

    _k2, _r2, failed = await _attempt(session, "fail-co")
    await fail_attempt(session, failed.id)
    await session.commit()
    with pytest.raises(ExecutionStatusError, match="status=failed"):
        await accept_attempt_research(
            session,
            attempt_id=failed.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )


@pytest.mark.asyncio
async def test_worker_uses_its_own_session_not_the_request_session(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "sess-co")
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    seen_sessions: list[AsyncSession] = []
    original = execute_attempt_research

    async def _capture(worker_session, **kwargs):
        seen_sessions.append(worker_session)
        return await original(worker_session, **kwargs)

    router, _sources = _router(RecordingSource("case_knowledge"))
    set_research_router_factory(lambda _session: router)
    from app.services.research import worker as worker_mod

    worker_mod.execute_attempt_research = _capture  # type: ignore[method-assign]
    try:
        await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        await run_research_claim(attempt.id)
    finally:
        worker_mod.execute_attempt_research = original
        set_research_router_factory(None)

    assert seen_sessions
    assert all(item is not session for item in seen_sessions)


@pytest.mark.asyncio
async def test_http_start_returns_before_gated_source_finishes(
    client: AsyncClient,
):
    entered = asyncio.Event()
    gate = asyncio.Event()

    class GatedSource:
        source_type = "customer_knowledge"
        provider_id = "fake"

        async def research(self, need: ResearchNeed, context: ResearchContext):
            entered.set()
            await gate.wait()
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="customer_knowledge",
                    status="found",
                    excerpt="skattesats 32%",
                    locator="p. 14",
                )
            ]

    registry = ResearchSourceRegistry()
    registry.register(GatedSource())
    set_research_router_factory(lambda _session: ResearchRouter(registry))
    try:
        run = await _create_run(client)
        attempt = await _create_attempt(client, run["id"])
        started = await client.post(
            f"/execution/attempts/{attempt['id']}/research",
            json={"research_plan": RESEARCH_PLAN},
        )
        assert started.status_code == 202, started.text
        assert started.json()["status"] in {"created", "researching"}
        await asyncio.wait_for(entered.wait(), timeout=2)
        still = await client.get(f"/execution/attempts/{attempt['id']}")
        assert still.json()["status"] in {"created", "researching"}
        gate.set()
        await wait_research_workers()
        done = await client.get(f"/execution/attempts/{attempt['id']}")
        assert done.json()["status"] == "ready"
    finally:
        gate.set()
        set_research_router_factory(None)


@pytest.mark.asyncio
async def test_due_claim_loop_completes_unclaimed_work(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "due-co")
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    router, sources = _router(RecordingSource("case_knowledge"))
    set_research_router_factory(lambda _session: router)
    try:
        status = await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        assert status == "202"
        assert await run_due_research_claims() == 1
    finally:
        set_research_router_factory(None)
    async with factory() as check:
        row = await get_attempt(check, attempt.id)
    assert row.status == "ready"
    assert sources[0].calls == 1


@pytest.mark.asyncio
async def test_release_clears_ownership(worker_db):
    session, _factory = worker_db
    _kund, _run, attempt = await _attempt(session, "rel-co")
    await enqueue_research_claim(
        session,
        attempt.id,
        start_request=start_request_payload(
            research_objective=None,
            research_context={},
            research_plan={"needs": []},
        ),
    )
    claimed = await claim_research_lease(session, attempt.id, worker_id="w1")
    assert claimed is not None
    await release_research_lease(session, attempt.id, lease_token=claimed.lease_token)
    await session.commit()
    again = await claim_research_lease(session, attempt.id, worker_id="w2")
    assert again is not None
    assert again.worker_id == "w2"
