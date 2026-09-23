"""Durable research claims: start, lease, reclaim, no duplicate runs."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database.base import Base
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionResearchClaim,
    Kund,
    ResearchNeedExecution,
    ResearchProgressEvent,
    ResearchRuntimeNeed,
)
from app.database.sqlite import async_engine_kwargs, register_sqlite_pragmas
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
from app.services.research.assessment import ProgrammaticResearchAssessor
from app.services.research.claims import (
    claim_research_lease,
    enqueue_research_claim,
    list_claimable_attempt_ids,
    release_research_lease,
    start_request_payload,
)
from app.services.research.completeness import ProgrammaticResearchCompletenessReviewer
from app.services.research.composition import (
    set_completeness_reviewer_factory,
    set_follow_up_planner_factory,
    set_research_assessor_factory,
    set_research_router_factory,
)
from app.services.research.execution import execute_attempt_research
from app.services.research.followup import NoOpFollowUpPlanner
from app.services.research.models import (
    ResearchContext,
    ResearchNeed,
    ResearchPlan,
    research_evidence,
)
from app.services.research.plan import research_plan_to_snapshot
from app.services.research.planner import FakeResearchPlanner, ResearchNeedDraft
from app.services.research.progress import list_research_progress_events
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.router import ResearchRouter
from app.services.research_worker import (
    accept_attempt_research,
    reset_research_worker,
    run_due_research_claims,
    run_research_claim,
    set_research_schedule_hook,
    set_research_session_factory,
    start_research_reclaim_loop,
    stop_research_reclaim_loop,
    wait_research_workers,
)
from tests.test_execution_api import RESEARCH_PLAN, _create_attempt, _create_run
from tests.test_research_execution import RecordingSource, _need, _router


@pytest.fixture
async def worker_db(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/research-worker.sqlite"
    engine = create_async_engine(url, **async_engine_kwargs(url))
    register_sqlite_pragmas(engine, url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_research_session_factory(factory)
    set_research_schedule_hook(lambda _attempt_id: None)
    set_research_assessor_factory(ProgrammaticResearchAssessor)
    set_follow_up_planner_factory(NoOpFollowUpPlanner)
    set_completeness_reviewer_factory(ProgrammaticResearchCompletenessReviewer)
    async with factory() as session:
        yield session, factory
    await wait_research_workers()
    reset_research_worker()
    set_research_assessor_factory(None)
    set_follow_up_planner_factory(None)
    set_completeness_reviewer_factory(None)
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


async def _expire_until_claimable(
    factory: async_sessionmaker[AsyncSession], attempt_id: str
) -> None:
    """Keep the lease expired until reclaim can observe it.

    A heartbeat renew can overwrite a single expire. Re-apply until the
    Attempt is claimable so the second worker actually starts.
    """
    deadline = utc_now() + timedelta(seconds=2)
    while utc_now() < deadline:
        async with factory() as expire:
            row = await expire.get(ExecutionResearchClaim, attempt_id)
            assert row is not None
            row.lease_expires_at = utc_now() - timedelta(seconds=1)
            await expire.commit()
        async with factory() as check:
            if attempt_id in await list_claimable_attempt_ids(check):
                return
        await asyncio.sleep(0.02)
    raise AssertionError(f"attempt {attempt_id} never became claimable")


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
    from app.services import research_worker as worker_mod

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
    set_research_assessor_factory(ProgrammaticResearchAssessor)
    set_follow_up_planner_factory(NoOpFollowUpPlanner)
    set_completeness_reviewer_factory(ProgrammaticResearchCompletenessReviewer)
    try:
        run = await _create_run(client)
        attempt = await _create_attempt(client, run["id"])
        started = await client.post(
            f"/execution/attempts/{attempt['id']}/research",
            json={
                "research_plan": {
                    "needs": [RESEARCH_PLAN["needs"][0]],
                }
            },
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
        set_research_assessor_factory(None)
        set_follow_up_planner_factory(None)
        set_completeness_reviewer_factory(None)


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
        await wait_research_workers()
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


@pytest.mark.asyncio
async def test_due_claim_loop_does_not_await_reclaimed_work_inline(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "poll-co")
    entered = asyncio.Event()
    gate = asyncio.Event()

    class GatedSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need: ResearchNeed, context: ResearchContext):
            entered.set()
            await gate.wait()
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="found",
                    excerpt="skattesats 32%",
                    locator="p. 14",
                )
            ]

    registry = ResearchSourceRegistry()
    registry.register(GatedSource())
    set_research_router_factory(lambda _session: ResearchRouter(registry))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    try:
        status = await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        assert status == "202"
        started = asyncio.get_running_loop().time()
        assert await run_due_research_claims() == 1
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert elapsed < 0.5
        async with factory() as check:
            row = await get_attempt(check, attempt.id)
        assert row.status in {"created", "researching"}
    finally:
        gate.set()
        await wait_research_workers()
        set_research_router_factory(None)


@pytest.mark.asyncio
async def test_lease_loss_fences_old_worker_after_second_claimant(
    worker_db, monkeypatch
):
    session, factory = worker_db
    monkeypatch.setattr(settings, "research_claim_lease_seconds", 0.3)
    _kund, _run, attempt = await _attempt(session, "fence-co")
    entered = asyncio.Event()
    gate = asyncio.Event()
    first_retrieve = True

    class GatedSource:
        source_type = "case_knowledge"
        provider_id = "fake"
        calls = 0

        async def research(self, need: ResearchNeed, context: ResearchContext):
            self.calls += 1
            nonlocal first_retrieve
            if first_retrieve:
                first_retrieve = False
                entered.set()
                await gate.wait()
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="found",
                    excerpt="skattesats 32%",
                    locator="p. 14",
                )
            ]

    source = GatedSource()
    registry = ResearchSourceRegistry()
    registry.register(source)
    set_research_router_factory(lambda _session: ResearchRouter(registry))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    try:
        await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        first = asyncio.create_task(run_research_claim(attempt.id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        # Keep the first worker's fast heartbeat, but give the replacement a
        # normal lease. Only the explicit expiry below should cause lease loss.
        monkeypatch.setattr(settings, "research_claim_lease_seconds", 60)
        await _expire_until_claimable(factory, attempt.id)
        second = asyncio.create_task(run_research_claim(attempt.id))
        await asyncio.wait_for(second, timeout=5)
        await asyncio.wait_for(first, timeout=5)
        async with factory() as check:
            done = await get_attempt(check, attempt.id)
            items = (
                await check.execute(select(func.count()).select_from(EvidenceSetItem))
            ).scalar()
            claimable = await list_claimable_attempt_ids(check)
        assert done.status == "ready"
        assert items == 1
        assert claimable == []
        assert source.calls >= 1
    finally:
        gate.set()
        await wait_research_workers()
        set_research_router_factory(None)


@pytest.mark.asyncio
async def test_setup_failure_fail_closes_attempt(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "setup-co")

    class BoomAssessor:
        def __init__(self) -> None:
            raise RuntimeError("assessor catalog missing")

    router, sources = _router(RecordingSource("case_knowledge"))
    set_research_router_factory(lambda _session: router)
    set_research_assessor_factory(BoomAssessor)
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    try:
        status = await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        assert status == "202"
        await run_research_claim(attempt.id)
        await run_due_research_claims()
        await wait_research_workers()
    finally:
        set_research_router_factory(None)
        set_research_assessor_factory(ProgrammaticResearchAssessor)
    async with factory() as check:
        row = await get_attempt(check, attempt.id)
        events = await list_research_progress_events(check, attempt.id)
        claimable = await list_claimable_attempt_ids(check)
    types = _event_types(events)
    assert row.status == "failed"
    assert claimable == []
    assert sources[0].calls == 0
    assert "research_failed" in types
    assert "research_frozen_ready" not in types
    assert types[-1] == "research_failed"


@pytest.mark.asyncio
async def test_stop_reclaim_loop_does_not_fail_inflight_research(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "stop-co")
    entered = asyncio.Event()
    gate = asyncio.Event()

    class GatedSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need: ResearchNeed, context: ResearchContext):
            entered.set()
            await gate.wait()
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="found",
                    excerpt="skattesats 32%",
                    locator="p. 14",
                )
            ]

    registry = ResearchSourceRegistry()
    registry.register(GatedSource())
    set_research_router_factory(lambda _session: ResearchRouter(registry))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    stop = None
    try:
        await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        assert await run_due_research_claims() == 1
        await asyncio.wait_for(entered.wait(), timeout=2)
        stop = start_research_reclaim_loop()
        await stop_research_reclaim_loop(stop)
        stop = None
        assert await run_due_research_claims() == 0
        async with factory() as check:
            paused = await get_attempt(check, attempt.id)
        assert paused.status in {"created", "researching"}
        gate.set()
        await wait_research_workers()
        async with factory() as check:
            events = await list_research_progress_events(check, attempt.id)
            done = await get_attempt(check, attempt.id)
        types = _event_types(events)
        assert done.status == "ready"
        assert "research_failed" not in types
        assert types.count("research_frozen_ready") == 1
        assert types[-1] == "research_frozen_ready"
    finally:
        gate.set()
        if stop is not None:
            await stop_research_reclaim_loop(stop)
        set_research_router_factory(None)


def _event_types(events: list[ResearchProgressEvent]) -> list[str]:
    return [row.event_type for row in events]


@pytest.mark.asyncio
async def test_worker_emits_progress_events_without_request_context(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "prog-worker")
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    router, _sources = _router(RecordingSource("case_knowledge"))
    set_research_router_factory(lambda _session: router)
    try:
        status = await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective="Kartlägg kommunens skattesats",
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        assert status == "202"
        await run_research_claim(attempt.id)
        await run_research_claim(attempt.id)
    finally:
        set_research_router_factory(None)

    async with factory() as check:
        events = await list_research_progress_events(check, attempt.id)
        row = await get_attempt(check, attempt.id)
    types = _event_types(events)
    assert row.status == "ready"
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert types[0] == "objective_accepted"
    assert "initial_plan_accepted" in types
    assert "research_need_planned" in types
    assert "need_queued" in types
    assert "need_running" in types
    assert "evidence_found" in types
    assert "need_completed" in types
    assert "local_assessment_persisted" in types
    assert types[-1] == "research_frozen_ready"
    first = [(event.id, event.sequence, event.event_type) for event in events]
    async with factory() as again:
        repeated = await list_research_progress_events(again, attempt.id)
    assert [(event.id, event.sequence, event.event_type) for event in repeated] == first


@pytest.mark.asyncio
async def test_lease_loss_does_not_emit_research_failed(worker_db, monkeypatch):
    session, factory = worker_db
    monkeypatch.setattr(settings, "research_claim_lease_seconds", 0.3)
    _kund, _run, attempt = await _attempt(session, "prog-fence")
    entered = asyncio.Event()
    gate = asyncio.Event()
    first_retrieve = True

    class GatedSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need: ResearchNeed, context: ResearchContext):
            nonlocal first_retrieve
            if first_retrieve:
                first_retrieve = False
                entered.set()
                await gate.wait()
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="found",
                    excerpt="skattesats 32%",
                    locator="p. 14",
                )
            ]

    registry = ResearchSourceRegistry()
    registry.register(GatedSource())
    set_research_router_factory(lambda _session: ResearchRouter(registry))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    try:
        await accept_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=None,
            research_context={},
            research_plan=research_plan_to_snapshot(plan),
        )
        first = asyncio.create_task(run_research_claim(attempt.id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        # Keep the first worker's fast heartbeat, but give the replacement a
        # normal lease. Only the explicit expiry below should cause lease loss.
        monkeypatch.setattr(settings, "research_claim_lease_seconds", 60)
        await _expire_until_claimable(factory, attempt.id)
        second = asyncio.create_task(run_research_claim(attempt.id))
        await asyncio.wait_for(second, timeout=5)
        await asyncio.wait_for(first, timeout=5)
        async with factory() as check:
            events = await list_research_progress_events(check, attempt.id)
            done = await get_attempt(check, attempt.id)
    finally:
        gate.set()
        await wait_research_workers()
        set_research_router_factory(None)

    types = _event_types(events)
    assert done.status == "ready"
    assert "research_failed" not in types
    assert types.count("research_frozen_ready") == 1
    assert types[-1] == "research_frozen_ready"


@pytest.mark.asyncio
async def test_fenced_exception_without_cancel_does_not_fail_close(worker_db):
    session, factory = worker_db
    _kund, _run, attempt = await _attempt(session, "prog-fence-exc")
    await session.commit()
    entered = asyncio.Event()
    gate = asyncio.Event()
    lease_lost = asyncio.Event()

    class BoomAfterFence:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need: ResearchNeed, context: ResearchContext):
            entered.set()
            await gate.wait()
            raise RuntimeError("stale after fence")

    router, _sources = _router(BoomAfterFence())
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    try:
        task = asyncio.create_task(
            execute_attempt_research(
                session,
                attempt_id=attempt.id,
                research_plan=plan,
                router=router,
                session_factory=factory,
                lease_lost=lease_lost,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        lease_lost.set()
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
    finally:
        gate.set()

    async with factory() as check:
        events = await list_research_progress_events(check, attempt.id)
        row = await get_attempt(check, attempt.id)
    types = _event_types(events)
    assert row.status == "researching"
    assert "need_failed" not in types
    assert "research_failed" not in types
    assert "research_frozen_ready" not in types
