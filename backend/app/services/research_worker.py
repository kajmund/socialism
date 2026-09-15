"""In-process worker that claims Attempt research and runs the existing loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.llm.research_assessment import build_llm_research_assessor
from app.llm.research_completeness import build_llm_research_completeness_reviewer
from app.llm.research_followup import build_llm_follow_up_planner
from app.llm.research_planner import build_llm_research_planner
from app.services import jobs as jobs_service
from app.services.execution.errors import ExecutionStatusError
from app.services.execution.service import get_attempt, get_run, new_id, set_attempt_snapshots
from app.services.research.claims import (
    claim_research_lease,
    enqueue_research_claim,
    list_claimable_attempt_ids,
    release_research_lease,
    renew_research_lease,
    start_request_payload,
)
from app.services.research.composition import (
    build_standard_research_router,
    require_research_router_ready,
    resolve_completeness_reviewer,
    resolve_follow_up_planner,
    resolve_research_assessor,
    resolve_research_planner,
)
from app.services.research.execution import execute_attempt_research, fail_incomplete_research
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.plan import research_plan_from_snapshot, research_plan_to_snapshot
from app.services.research.planner import (
    InvalidResearchObjectiveError,
    ResearchObjective,
    require_research_objective,
    research_objective_to_snapshot,
)

logger = logging.getLogger(__name__)

_session_factory: async_sessionmaker[AsyncSession] | None = None
_schedule_hook: Callable[[str], None] | None = None
_inflight: set[asyncio.Task[None]] = set()
_loop_task: asyncio.Task[None] | None = None
_accepting_work = True


def set_research_session_factory(
    factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Tests inject an in-memory factory. Production uses the jobs factory."""
    global _session_factory
    _session_factory = factory


def research_session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory or jobs_service.job_session_factory()


def set_research_schedule_hook(hook: Callable[[str], None] | None) -> None:
    global _schedule_hook
    _schedule_hook = hook


def enqueue_research(attempt_id: str) -> None:
    if _schedule_hook is not None:
        _schedule_hook(attempt_id)
        return
    schedule_research(attempt_id)


def schedule_research(attempt_id: str) -> None:
    if not _accepting_work:
        return

    async def _deferred() -> None:
        await asyncio.sleep(0)
        await run_research_claim(attempt_id)

    task = asyncio.create_task(_deferred(), name=f"research:{attempt_id}")
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def wait_research_workers() -> None:
    pending = list(_inflight)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def reset_research_worker() -> None:
    global _accepting_work
    _accepting_work = True
    set_research_session_factory(None)
    set_research_schedule_hook(None)


async def accept_attempt_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    research_objective: str | None,
    research_context: dict[str, Any],
    research_plan: dict[str, Any] | None,
) -> str:
    """Persist start input and one claim. Returns the HTTP status to emit."""
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "ready":
        return "200"
    if attempt.status not in {"created", "researching"}:
        raise ExecutionStatusError(
            f"Cannot start research on attempt {attempt.id} with status={attempt.status}"
        )
    require_research_router_ready()
    plan = None
    if research_plan is not None:
        plan = research_plan_from_snapshot(research_plan)
    objective = None
    if research_objective is not None:
        objective = ResearchObjective(
            objective=require_research_objective(research_objective),
            context=dict(research_context),
        )
    if plan is not None:
        await set_attempt_snapshots(
            session,
            attempt_id=attempt_id,
            research_plan_snapshot=research_plan_to_snapshot(plan),
        )
    if objective is not None:
        await set_attempt_snapshots(
            session,
            attempt_id=attempt_id,
            research_objective_snapshot=research_objective_to_snapshot(objective),
        )
    await enqueue_research_claim(
        session,
        attempt_id,
        start_request=start_request_payload(
            research_objective=research_objective,
            research_context=research_context,
            research_plan=research_plan,
        ),
    )
    await session.commit()
    enqueue_research(attempt_id)
    return "202"


async def run_research_claim(attempt_id: str) -> None:
    factory = research_session_factory()
    worker_id = new_id()
    lease_token: str | None = None
    async with factory() as session:
        claimed = await claim_research_lease(session, attempt_id, worker_id=worker_id)
        if claimed is None:
            await session.commit()
            return
        lease_token = claimed.lease_token
        start_request = dict(claimed.start_request or {})
        await session.commit()
    stop = asyncio.Event()
    lease_lost = asyncio.Event()
    execute_task = asyncio.create_task(
        _execute_claimed_research(
            factory,
            attempt_id=attempt_id,
            start_request=start_request,
            lease_lost=lease_lost,
        ),
        name=f"research-execute:{attempt_id}",
    )
    heartbeat = asyncio.create_task(
        _heartbeat_lease(
            attempt_id,
            lease_token=lease_token or "",
            stop=stop,
            lease_lost=lease_lost,
            execute_task=execute_task,
        ),
        name=f"research-heartbeat:{attempt_id}",
    )
    try:
        await execute_task
    except asyncio.CancelledError:
        if lease_lost.is_set():
            return
        raise
    except Exception:
        logger.exception("Background research failed for attempt %s", attempt_id)
    finally:
        stop.set()
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        if lease_lost.is_set() or lease_token is None:
            return
        async with factory() as session:
            await release_research_lease(
                session, attempt_id, lease_token=lease_token
            )
            await session.commit()


async def run_due_research_claims() -> int:
    if not _accepting_work:
        return 0
    factory = research_session_factory()
    async with factory() as session:
        attempt_ids = await list_claimable_attempt_ids(session)
    scheduled = 0
    for attempt_id in attempt_ids:
        if not _accepting_work:
            break
        schedule_research(attempt_id)
        scheduled += 1
    return scheduled


async def research_reclaim_loop(*, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await run_due_research_claims()
        except Exception:
            logger.exception("Research reclaim loop failed")
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.research_worker_poll_seconds
            )
        except TimeoutError:
            continue


def start_research_reclaim_loop() -> asyncio.Event:
    global _loop_task, _accepting_work
    _accepting_work = True
    stop = asyncio.Event()

    async def _run() -> None:
        await research_reclaim_loop(stop=stop)

    _loop_task = asyncio.create_task(_run(), name="research-reclaim-loop")
    return stop


async def stop_research_reclaim_loop(stop: asyncio.Event) -> None:
    global _loop_task, _accepting_work
    _accepting_work = False
    stop.set()
    task = _loop_task
    _loop_task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _heartbeat_lease(
    attempt_id: str,
    *,
    lease_token: str,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
    execute_task: asyncio.Task[None],
) -> None:
    interval = max(settings.research_claim_lease_seconds / 3, 0.05)
    factory = research_session_factory()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        async with factory() as session:
            renewed = await renew_research_lease(
                session, attempt_id, lease_token=lease_token
            )
            await session.commit()
        if not renewed:
            logger.warning("Research lease lost for attempt %s", attempt_id)
            lease_lost.set()
            execute_task.cancel()
            return


async def _fail_setup_research(
    factory: async_sessionmaker[AsyncSession], attempt_id: str
) -> None:
    async with factory() as session:
        await fail_incomplete_research(session, attempt_id=attempt_id)


async def _execute_claimed_research(
    factory: async_sessionmaker[AsyncSession],
    *,
    attempt_id: str,
    start_request: dict[str, Any],
    lease_lost: asyncio.Event,
) -> None:
    async with factory() as session:
        try:
            bound = await _bind_claimed_research(
                session, attempt_id=attempt_id, start_request=start_request
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if not lease_lost.is_set():
                await session.rollback()
                await _fail_setup_research(factory, attempt_id)
            raise
        if bound is None:
            return
        await execute_attempt_research(
            session,
            attempt_id=attempt_id,
            research_plan=bound["plan"],
            research_objective=bound["objective"],
            research_planner=bound["research_planner"],
            router_factory=build_standard_research_router,
            assessor=bound["assessor"],
            planner=bound["planner"],
            completeness_reviewer=bound["completeness_reviewer"],
            question_graph=SqlQuestionEvidenceGraph(),
            session_factory=factory,
            lease_lost=lease_lost,
        )


async def _bind_claimed_research(
    session: AsyncSession,
    *,
    attempt_id: str,
    start_request: dict[str, Any],
) -> dict[str, Any] | None:
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "ready":
        return None
    if attempt.status not in {"created", "researching"}:
        return None
    run = await get_run(session, attempt.run_id)
    raw_plan = start_request.get("research_plan")
    if attempt.research_plan_snapshot is not None:
        plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
    elif isinstance(raw_plan, dict):
        plan = research_plan_from_snapshot(raw_plan)
    else:
        plan = None
    objective = None
    raw_objective = start_request.get("research_objective")
    if attempt.research_objective_snapshot is None and raw_objective is not None:
        context = start_request.get("research_context") or {}
        if not isinstance(context, dict):
            raise InvalidResearchObjectiveError("research_context must be an object")
        objective = ResearchObjective(
            objective=require_research_objective(str(raw_objective)),
            context=dict(context),
        )
    require_research_router_ready()
    assessor = resolve_research_assessor()
    if assessor is None:
        assessor = await build_llm_research_assessor(
            session, customer_id=run.customer_id, module=run.module
        )
    planner = resolve_follow_up_planner()
    if planner is None:
        planner = await build_llm_follow_up_planner(
            session, customer_id=run.customer_id, module=run.module
        )
    research_planner = resolve_research_planner()
    if research_planner is None and plan is None:
        research_planner = await build_llm_research_planner(
            session, customer_id=run.customer_id, module=run.module
        )
    completeness_reviewer = resolve_completeness_reviewer()
    if completeness_reviewer is None:
        completeness_reviewer = await build_llm_research_completeness_reviewer(
            session, customer_id=run.customer_id, module=run.module
        )
    return {
        "plan": plan,
        "objective": objective,
        "research_planner": research_planner,
        "assessor": assessor,
        "planner": planner,
        "completeness_reviewer": completeness_reviewer,
    }
