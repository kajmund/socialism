"""Queue graph revalidation after committed claims, off the retrieval path.

Evidence retrieval, assessment, and synthesis do not read
``EvidenceSetRevalidation``. The current document's evidence item is built
from the persisted claims. This worker marks older frozen snapshots later.
A missing row means "not reviewed yet", never "clear".
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.models import GraphRevalidationWork
from app.jev.evaluation import (
    EVALUATOR_GRAPH_REVALIDATION,
    EVALUATOR_GRAPH_REVALIDATION_POLICY,
    EVALUATOR_GRAPH_REVALIDATION_VERSION,
    canonical_json,
    sha256_text,
)
from app.jev.system import HttpJevSystemOne, JevSystemOne
from app.observability.research import research_obs_scope
from app.services.execution.service import new_id, utc_now
from app.services.knowledge.events import list_graph_events
from app.services.knowledge.revalidation import revalidate_after_events

logger = logging.getLogger(__name__)

PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"

Performer = Callable[[AsyncSession, GraphRevalidationWork], Awaitable[None]]

_session_factory: async_sessionmaker[AsyncSession] | None = None
_performer: Performer | None = None
_scheduling = False
_schedule_hook: Callable[[str], None] | None = None
_inflight: set[asyncio.Task[None]] = set()


def set_graph_revalidation_session_factory(
    factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    global _session_factory
    _session_factory = factory


def graph_revalidation_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is not None:
        return _session_factory
    # research_worker imports this module, so its factory is resolved at call time.
    from app.services.research_worker import research_session_factory

    return research_session_factory()


def set_graph_revalidation_performer(performer: Performer | None) -> None:
    global _performer
    _performer = performer


def set_graph_revalidation_schedule_hook(hook: Callable[[str], None] | None) -> None:
    global _schedule_hook
    _schedule_hook = hook


def set_graph_revalidation_scheduling(enabled: bool) -> None:
    global _scheduling
    _scheduling = enabled


def reset_graph_revalidation_worker() -> None:
    global _scheduling
    _scheduling = False
    set_graph_revalidation_session_factory(None)
    set_graph_revalidation_performer(None)
    set_graph_revalidation_schedule_hook(None)


def revalidation_idempotency_key(
    *,
    customer_id: int,
    document_version_id: str | None,
    claim_ids: list[str],
    relationship_ids: list[str],
) -> str:
    payload = {
        "customer_id": customer_id,
        "document_version_id": document_version_id or "",
        "claim_ids": sorted(claim_ids),
        "relationship_ids": sorted(relationship_ids),
        "evaluator_id": EVALUATOR_GRAPH_REVALIDATION,
        "evaluator_version": EVALUATOR_GRAPH_REVALIDATION_VERSION,
        "policy_version": EVALUATOR_GRAPH_REVALIDATION_POLICY,
        "model": settings.jev_model,
        "impact_threshold": settings.revalidation_impact_threshold,
        "clear_threshold": settings.revalidation_clear_threshold,
    }
    return sha256_text(canonical_json(payload))


async def enqueue_graph_revalidation(
    session: AsyncSession,
    *,
    customer_id: int,
    document_id: str | None,
    document_version_id: str | None,
    claim_ids: list[str],
    relationship_ids: list[str],
) -> GraphRevalidationWork | None:
    """Insert one pending row in the caller's transaction. Does not commit."""
    if not claim_ids and not relationship_ids:
        return None
    key = revalidation_idempotency_key(
        customer_id=customer_id,
        document_version_id=document_version_id,
        claim_ids=claim_ids,
        relationship_ids=relationship_ids,
    )
    existing = await _work_by_key(session, key)
    if existing is not None:
        if existing.status == FAILED:
            existing.status = PENDING
            existing.error = None
            existing.lease_token = None
            existing.lease_expires_at = None
            existing.worker_id = None
            existing.finished_at = None
            await session.flush()
        return existing
    row = GraphRevalidationWork(
        id=new_id(),
        customer_id=customer_id,
        idempotency_key=key,
        document_id=document_id,
        document_version_id=document_version_id,
        claim_ids=list(claim_ids),
        relationship_ids=list(relationship_ids),
        status=PENDING,
        attempts=0,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        loaded = await _work_by_key(session, key)
        if loaded is None:
            raise
        return loaded
    return row


def schedule_graph_revalidation(work_id: str) -> None:
    """Start one worker if the reclaim loop is accepting work. Never awaits it."""
    if _schedule_hook is not None:
        _schedule_hook(work_id)
        return
    if not _scheduling:
        return
    task = asyncio.create_task(
        run_graph_revalidation_work(work_id),
        name=f"graph-revalidation:{work_id}",
    )
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def wait_graph_revalidation_workers() -> None:
    pending = list(_inflight)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def run_due_graph_revalidations() -> int:
    if not _scheduling and _schedule_hook is None:
        return 0
    factory = graph_revalidation_session_factory()
    async with factory() as session:
        work_ids = await _due_work_ids(session)
    scheduled = 0
    for work_id in work_ids:
        schedule_graph_revalidation(work_id)
        scheduled += 1
    return scheduled


async def run_graph_revalidation_work(work_id: str) -> None:
    factory = graph_revalidation_session_factory()
    worker_id = new_id()
    async with factory() as session:
        claimed = await _claim(session, work_id, worker_id=worker_id)
        lease_token = None if claimed is None else claimed.lease_token
        await session.commit()
    if lease_token is None:
        return
    stop = asyncio.Event()
    lease_lost = asyncio.Event()
    execute_task = asyncio.create_task(
        _execute_claimed(
            factory,
            work_id=work_id,
            lease_token=lease_token,
            lease_lost=lease_lost,
        ),
        name=f"graph-revalidation-execute:{work_id}",
    )
    heartbeat = asyncio.create_task(
        _heartbeat(
            work_id,
            lease_token=lease_token,
            stop=stop,
            lease_lost=lease_lost,
            execute_task=execute_task,
        ),
        name=f"graph-revalidation-heartbeat:{work_id}",
    )
    try:
        await execute_task
    except asyncio.CancelledError:
        if not lease_lost.is_set():
            raise
    finally:
        stop.set()
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass


async def _execute_claimed(
    factory: async_sessionmaker[AsyncSession],
    *,
    work_id: str,
    lease_token: str,
    lease_lost: asyncio.Event,
) -> None:
    started = time.perf_counter()
    async with factory() as session:
        work = await session.get(GraphRevalidationWork, work_id)
        if work is None or work.lease_token != lease_token:
            return
        _log(
            "graph_revalidation_started",
            work,
            events_total=0,
            events_skipped=0,
            events_evaluated=0,
            events_remaining=0,
        )
        try:
            summary = await _run_performer(session, work)
        except asyncio.CancelledError:
            if lease_lost.is_set():
                return
            raise
        except Exception as exc:  # noqa: BLE001 — any downstream failure stays retryable
            await session.rollback()
            if lease_lost.is_set():
                return
            await _mark_retryable_failure(factory, work_id, lease_token, exc, started)
            return
    if lease_lost.is_set():
        return
    await _mark_succeeded(factory, work_id, lease_token, summary, started)


async def _run_performer(
    session: AsyncSession,
    work: GraphRevalidationWork,
) -> dict[str, int]:
    if _performer is not None:
        await _performer(session, work)
        return {
            "events_total": 0,
            "events_skipped": 0,
            "events_evaluated": 0,
            "jev_requested": 0,
            "jev_executed": 0,
            "jev_reused": 0,
        }
    return await _revalidate_committed_graph(session, work)


async def _revalidate_committed_graph(
    session: AsyncSession,
    work: GraphRevalidationWork,
) -> dict[str, int]:
    event_ids = await _event_ids(session, work)
    _log(
        "graph_revalidation_progress",
        work,
        events_total=len(event_ids),
        events_skipped=0,
        events_evaluated=0,
        events_remaining=len(event_ids),
        elapsed_ms=0,
    )
    with research_obs_scope() as stats:
        await revalidate_after_events(session, event_ids, jev=_jev())
    return {
        "events_total": len(event_ids),
        "events_skipped": stats.graph_revalidation_skipped,
        "events_evaluated": stats.graph_revalidation_jev_required,
        "jev_requested": stats.jev_evaluation_requested,
        "jev_executed": stats.jev_evaluation_executed,
        "jev_reused": stats.jev_evaluation_reused,
    }


def _jev() -> JevSystemOne:
    return HttpJevSystemOne()


async def _event_ids(session: AsyncSession, work: GraphRevalidationWork) -> list[str]:
    seen: dict[str, None] = {}
    claim_ids = [item for item in work.claim_ids or [] if isinstance(item, str)]
    relationship_ids = [
        item for item in work.relationship_ids or [] if isinstance(item, str)
    ]
    for node_kind, node_ids in (
        ("claim", claim_ids),
        ("relationship", relationship_ids),
    ):
        for node_id in node_ids:
            events = await list_graph_events(
                session,
                customer_id=work.customer_id,
                node_kind=node_kind,
                node_id=node_id,
            )
            for event in events:
                seen.setdefault(event.id, None)
    return list(seen)


async def _claim(
    session: AsyncSession,
    work_id: str,
    *,
    worker_id: str,
) -> GraphRevalidationWork | None:
    now = utc_now()
    token = new_id()
    result = await session.execute(
        update(GraphRevalidationWork)
        .where(
            GraphRevalidationWork.id == work_id,
            GraphRevalidationWork.attempts < settings.graph_revalidation_max_attempts,
            or_(
                GraphRevalidationWork.status == PENDING,
                and_(
                    GraphRevalidationWork.status == RUNNING,
                    or_(
                        GraphRevalidationWork.lease_expires_at.is_(None),
                        GraphRevalidationWork.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .values(
            status=RUNNING,
            worker_id=worker_id,
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=settings.graph_revalidation_lease_seconds),
            started_at=now,
            attempts=GraphRevalidationWork.attempts + 1,
            error=None,
        )
    )
    if result.rowcount != 1:
        return None
    claimed = await session.get(GraphRevalidationWork, work_id)
    if claimed is not None:
        await session.refresh(claimed)
    return claimed


async def _heartbeat(
    work_id: str,
    *,
    lease_token: str,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
    execute_task: asyncio.Task[None],
) -> None:
    interval = max(settings.graph_revalidation_lease_seconds / 3, 0.05)
    factory = graph_revalidation_session_factory()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        async with factory() as session:
            renewed = await _renew(session, work_id, lease_token=lease_token)
            await session.commit()
        if not renewed:
            lease_lost.set()
            execute_task.cancel()
            return


async def _renew(session: AsyncSession, work_id: str, *, lease_token: str) -> bool:
    now = utc_now()
    result = await session.execute(
        update(GraphRevalidationWork)
        .where(
            GraphRevalidationWork.id == work_id,
            GraphRevalidationWork.lease_token == lease_token,
            GraphRevalidationWork.status == RUNNING,
            GraphRevalidationWork.lease_expires_at > now,
        )
        .values(
            lease_expires_at=now
            + timedelta(seconds=settings.graph_revalidation_lease_seconds)
        )
    )
    return result.rowcount == 1


async def _mark_succeeded(
    factory: async_sessionmaker[AsyncSession],
    work_id: str,
    lease_token: str,
    summary: dict[str, int],
    started: float,
) -> None:
    elapsed_ms = (time.perf_counter() - started) * 1000
    async with factory() as session:
        row = await session.get(GraphRevalidationWork, work_id)
        if row is None or row.lease_token != lease_token:
            return
        row.status = SUCCEEDED
        row.finished_at = utc_now()
        row.lease_token = None
        row.lease_expires_at = None
        row.worker_id = None
        row.error = None
        row.events_total = summary["events_total"]
        row.events_skipped = summary["events_skipped"]
        row.events_evaluated = summary["events_evaluated"]
        await session.commit()
        await session.refresh(row)
        remaining = max(
            summary["events_total"] - summary["events_skipped"] - summary["events_evaluated"],
            0,
        )
        _log(
            "graph_revalidation_completed",
            row,
            events_total=summary["events_total"],
            events_skipped=summary["events_skipped"],
            events_evaluated=summary["events_evaluated"],
            events_remaining=remaining,
            jev_requested=summary["jev_requested"],
            jev_executed=summary["jev_executed"],
            jev_reused=summary["jev_reused"],
            elapsed_ms=elapsed_ms,
        )


async def _mark_retryable_failure(
    factory: async_sessionmaker[AsyncSession],
    work_id: str,
    lease_token: str,
    exc: Exception,
    started: float,
) -> None:
    elapsed_ms = (time.perf_counter() - started) * 1000
    message = str(exc)[:500]
    async with factory() as session:
        row = await session.get(GraphRevalidationWork, work_id)
        if row is None or row.lease_token != lease_token:
            return
        retryable = row.attempts < settings.graph_revalidation_max_attempts
        row.status = PENDING if retryable else FAILED
        row.error = message
        row.finished_at = None if retryable else utc_now()
        row.lease_token = None
        row.lease_expires_at = None
        row.worker_id = None
        await session.commit()
        await session.refresh(row)
        logger.info(
            "graph_revalidation_failed customer_id=%s work_id=%s document_id=%s "
            "document_version_id=%s attempts=%s retryable=%s elapsed_ms=%.3f error=%s",
            row.customer_id,
            row.id,
            row.document_id or "",
            row.document_version_id or "",
            row.attempts,
            retryable,
            elapsed_ms,
            message,
        )


async def _due_work_ids(session: AsyncSession) -> list[str]:
    now = utc_now()
    rows = await session.scalars(
        select(GraphRevalidationWork.id)
        .where(
            GraphRevalidationWork.attempts < settings.graph_revalidation_max_attempts,
            or_(
                GraphRevalidationWork.status == PENDING,
                and_(
                    GraphRevalidationWork.status == RUNNING,
                    or_(
                        GraphRevalidationWork.lease_expires_at.is_(None),
                        GraphRevalidationWork.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .limit(32)
    )
    return list(rows)


async def _work_by_key(
    session: AsyncSession,
    key: str,
) -> GraphRevalidationWork | None:
    return await session.scalar(
        select(GraphRevalidationWork).where(GraphRevalidationWork.idempotency_key == key)
    )


def log_graph_revalidation_queued(work: GraphRevalidationWork) -> None:
    logger.info(
        "graph_revalidation_queued customer_id=%s work_id=%s document_id=%s "
        "document_version_id=%s claims=%s relationships=%s status=%s",
        work.customer_id,
        work.id,
        work.document_id or "",
        work.document_version_id or "",
        len(work.claim_ids or []),
        len(work.relationship_ids or []),
        work.status,
    )


def _log(
    event: str,
    work: GraphRevalidationWork,
    *,
    events_total: int,
    events_skipped: int,
    events_evaluated: int,
    events_remaining: int,
    jev_requested: int = 0,
    jev_executed: int = 0,
    jev_reused: int = 0,
    elapsed_ms: float = 0,
) -> None:
    logger.info(
        "%s customer_id=%s work_id=%s document_id=%s document_version_id=%s "
        "events_total=%s events_skipped=%s events_evaluated=%s events_remaining=%s "
        "jev_requested=%s jev_executed=%s jev_reused=%s elapsed_ms=%.3f",
        event,
        work.customer_id,
        work.id,
        work.document_id or "",
        work.document_version_id or "",
        events_total,
        events_skipped,
        events_evaluated,
        events_remaining,
        jev_requested,
        jev_executed,
        jev_reused,
        elapsed_ms,
    )
