"""Persisted research progress events. Domain tables stay source of truth.

Events summarize durable transitions for UX and reconnect. They never
duplicate full evidence/documents or carry model prompts / chain-of-thought.
Live fan-out is best-effort and must not roll back research.
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Literal, Self
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    EvidenceSetItem,
    ResearchAssessment,
    ResearchCompletenessPass,
    ResearchNeedExecution,
    ResearchProgressEvent,
    ResearchRuntimeNeed,
)
from app.realtime.research_progress_broadcast import research_progress_broadcast
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import ResearchObjective

logger = logging.getLogger(__name__)

PREVIEW_LIMIT = 160

ResearchProgressEventType = Literal[
    "objective_accepted",
    "initial_plan_accepted",
    "research_need_planned",
    "follow_up_need_derived",
    "global_need_derived",
    "need_queued",
    "need_running",
    "need_completed",
    "need_failed",
    "evidence_found",
    "evidence_not_found",
    "evidence_error",
    "local_assessment_persisted",
    "global_completeness_persisted",
    "capability_unavailable",
    "research_frozen_ready",
    "research_failed",
]

RESEARCH_PROGRESS_EVENT_TYPES: tuple[ResearchProgressEventType, ...] = (
    "objective_accepted",
    "initial_plan_accepted",
    "research_need_planned",
    "follow_up_need_derived",
    "global_need_derived",
    "need_queued",
    "need_running",
    "need_completed",
    "need_failed",
    "evidence_found",
    "evidence_not_found",
    "evidence_error",
    "local_assessment_persisted",
    "global_completeness_persisted",
    "capability_unavailable",
    "research_frozen_ready",
    "research_failed",
)

_EVIDENCE_EVENT_TYPES: dict[str, ResearchProgressEventType] = {
    "found": "evidence_found",
    "not_found": "evidence_not_found",
    "error": "evidence_error",
}

_BLOCKED_PAYLOAD_KEYS = frozenset(
    {
        "prompt",
        "prompts",
        "messages",
        "system",
        "chain_of_thought",
        "reasoning",
        "raw_prompt",
        "model_input",
    }
)

_pending: ContextVar[list[ResearchProgressEvent] | None] = ContextVar(
    "research_progress_pending", default=None
)


class ProgressTracker:
    """Collect events written in the current transaction for post-commit fan-out."""

    def __init__(self) -> None:
        self.events: list[ResearchProgressEvent] = []
        self._token = None
        self._owns = False

    def __enter__(self) -> Self:
        existing = _pending.get()
        if existing is not None:
            self.events = existing
            return self
        self.events = []
        self._token = _pending.set(self.events)
        self._owns = True
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._owns and self._token is not None:
            _pending.reset(self._token)
            self._token = None
            self._owns = False

    async def publish_committed(self) -> None:
        pending = list(self.events)
        self.events.clear()
        schedule_research_progress_delivery(pending)


def preview_text(value: str | None, *, limit: int = PREVIEW_LIMIT) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def sanitize_progress_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only small structured refs. Drop prompt / CoT-shaped keys."""
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _BLOCKED_PAYLOAD_KEYS:
            continue
        if isinstance(value, str):
            clean[key] = value
            continue
        if isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
            continue
        if isinstance(value, list):
            clean[key] = [
                item
                for item in value
                if isinstance(item, (str, int, float, bool)) or item is None
            ]
            continue
        if isinstance(value, dict):
            nested = sanitize_progress_payload(value)
            if nested:
                clean[key] = nested
    return clean


def progress_event_to_dict(row: ResearchProgressEvent) -> dict[str, Any]:
    return {
        "type": "research.progress",
        "id": row.id,
        "attempt_id": row.attempt_id,
        "sequence": row.sequence,
        "event_type": row.event_type,
        "payload": dict(row.payload or {}),
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


async def list_research_progress_events(
    session: AsyncSession,
    attempt_id: str,
    *,
    after_sequence: int = 0,
) -> list[ResearchProgressEvent]:
    result = await session.execute(
        select(ResearchProgressEvent)
        .where(
            ResearchProgressEvent.attempt_id == attempt_id,
            ResearchProgressEvent.sequence > after_sequence,
        )
        .order_by(ResearchProgressEvent.sequence)
    )
    return list(result.scalars().all())


async def get_research_progress_event_by_key(
    session: AsyncSession,
    attempt_id: str,
    idempotency_key: str,
) -> ResearchProgressEvent | None:
    result = await session.execute(
        select(ResearchProgressEvent).where(
            ResearchProgressEvent.attempt_id == attempt_id,
            ResearchProgressEvent.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def _next_sequence(session: AsyncSession, attempt_id: str) -> int:
    result = await session.execute(
        select(func.max(ResearchProgressEvent.sequence)).where(
            ResearchProgressEvent.attempt_id == attempt_id
        )
    )
    current = result.scalar_one()
    return 1 if current is None else int(current) + 1


def _track(event: ResearchProgressEvent) -> None:
    pending = _pending.get()
    if pending is None:
        return
    if any(existing.id == event.id for existing in pending):
        return
    pending.append(event)


async def append_research_progress_event(
    session: AsyncSession,
    *,
    attempt_id: str,
    event_type: ResearchProgressEventType,
    payload: dict[str, Any],
    idempotency_key: str,
) -> ResearchProgressEvent:
    """Insert one event after a durable transition. Same key returns the original."""
    if event_type not in RESEARCH_PROGRESS_EVENT_TYPES:
        raise ValueError(f"Unknown research progress event type: {event_type}")
    key = idempotency_key.strip()
    if not key:
        raise ValueError("idempotency_key is required")
    existing = await get_research_progress_event_by_key(session, attempt_id, key)
    if existing is not None:
        _track(existing)
        return existing
    row = ResearchProgressEvent(
        id=uuid4().hex,
        attempt_id=attempt_id,
        sequence=await _next_sequence(session, attempt_id),
        event_type=event_type,
        payload=sanitize_progress_payload(payload),
        idempotency_key=key,
    )
    session.add(row)
    await session.flush()
    _track(row)
    return row


def schedule_research_progress_delivery(
    events: list[ResearchProgressEvent],
) -> None:
    """Queue live fan-out after commit. Never blocks or fails research."""
    if not events:
        return
    payloads = [
        (event.attempt_id, progress_event_to_dict(event)) for event in events
    ]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception(
            "Research progress live delivery skipped: no running event loop"
        )
        return
    loop.create_task(
        _deliver_research_progress_payloads(payloads),
        name="research-progress-fanout",
    )


async def deliver_research_progress_events(
    events: list[ResearchProgressEvent],
) -> None:
    """Best-effort live fan-out. Persistence already committed; never raise."""
    schedule_research_progress_delivery(events)


async def _deliver_research_progress_payloads(
    payloads: list[tuple[str, dict[str, Any]]],
) -> None:
    for attempt_id, event in payloads:
        try:
            await research_progress_broadcast.publish(attempt_id, event)
        except Exception:
            logger.exception(
                "Research progress live delivery failed attempt=%s sequence=%s",
                attempt_id,
                event.get("sequence"),
            )


async def emit_objective_accepted(
    session: AsyncSession,
    *,
    attempt_id: str,
    objective: ResearchObjective,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=attempt_id,
        event_type="objective_accepted",
        idempotency_key="objective_accepted",
        payload={
            "objective_preview": preview_text(objective.objective),
        },
    )


async def emit_initial_plan_accepted(
    session: AsyncSession,
    *,
    attempt_id: str,
    plan: ResearchPlan,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=attempt_id,
        event_type="initial_plan_accepted",
        idempotency_key="initial_plan_accepted",
        payload={
            "need_ids": [need.id for need in plan.needs],
            "need_count": len(plan.needs),
        },
    )


async def emit_runtime_need_created(
    session: AsyncSession,
    *,
    attempt_id: str,
    need: ResearchRuntimeNeed | ResearchNeed,
) -> ResearchProgressEvent:
    if isinstance(need, ResearchNeed):
        need_id = need.id
        origin = "initial"
        wave_number = 0
        parent_id = None
        source_assessment_pass = None
        source_completeness_pass = None
        source_types = list(need.source_types)
        question = need.question
    else:
        need_id = need.research_need_id
        origin = need.origin
        wave_number = need.wave_number
        parent_id = need.parent_research_need_id
        source_assessment_pass = need.source_assessment_pass
        source_completeness_pass = need.source_completeness_pass
        source_types = list(need.source_types or [])
        question = need.question
    if origin == "derived":
        event_type: ResearchProgressEventType = "follow_up_need_derived"
        key = f"follow_up_need:{need_id}"
    elif origin == "global_completeness":
        event_type = "global_need_derived"
        key = f"global_need:{need_id}"
    else:
        event_type = "research_need_planned"
        key = f"need_planned:{need_id}"
    return await append_research_progress_event(
        session,
        attempt_id=attempt_id,
        event_type=event_type,
        idempotency_key=key,
        payload={
            "research_need_id": need_id,
            "origin": origin,
            "wave_number": wave_number,
            "parent_research_need_id": parent_id,
            "source_assessment_pass": source_assessment_pass,
            "source_completeness_pass": source_completeness_pass,
            "source_types": source_types,
            "question_preview": preview_text(question),
        },
    )


async def emit_need_queued(
    session: AsyncSession,
    *,
    execution: ResearchNeedExecution,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=execution.attempt_id,
        event_type="need_queued",
        idempotency_key=f"need_queued:{execution.research_need_id}",
        payload={
            "research_need_id": execution.research_need_id,
            "need_execution_id": execution.id,
        },
    )


async def emit_need_running(
    session: AsyncSession,
    *,
    execution: ResearchNeedExecution,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=execution.attempt_id,
        event_type="need_running",
        idempotency_key=f"need_running:{execution.research_need_id}",
        payload={
            "research_need_id": execution.research_need_id,
            "need_execution_id": execution.id,
        },
    )


async def emit_need_completed(
    session: AsyncSession,
    *,
    execution: ResearchNeedExecution,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=execution.attempt_id,
        event_type="need_completed",
        idempotency_key=f"need_completed:{execution.research_need_id}",
        payload={
            "research_need_id": execution.research_need_id,
            "need_execution_id": execution.id,
        },
    )


async def emit_need_failed(
    session: AsyncSession,
    *,
    execution: ResearchNeedExecution,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=execution.attempt_id,
        event_type="need_failed",
        idempotency_key=f"need_failed:{execution.research_need_id}",
        payload={
            "research_need_id": execution.research_need_id,
            "need_execution_id": execution.id,
        },
    )


async def emit_evidence_item(
    session: AsyncSession,
    *,
    attempt_id: str,
    item: EvidenceSetItem,
) -> ResearchProgressEvent:
    status = item.status
    event_type = _EVIDENCE_EVENT_TYPES.get(status)
    if event_type is None:
        raise ValueError(f"Unknown evidence status: {status}")
    evidence_key = item.original_evidence_id or item.id
    return await append_research_progress_event(
        session,
        attempt_id=attempt_id,
        event_type=event_type,
        idempotency_key=f"evidence:{evidence_key}",
        payload={
            "evidence_item_id": item.id,
            "original_evidence_id": item.original_evidence_id,
            "research_need_id": item.research_need_id,
            "source_type": item.source_type,
            "provider": item.provider,
            "status": item.status,
        },
    )


async def emit_assessment_persisted(
    session: AsyncSession,
    *,
    assessment: ResearchAssessment,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=assessment.attempt_id,
        event_type="local_assessment_persisted",
        idempotency_key=f"assessment:{assessment.assessment_pass}",
        payload={
            "assessment_id": assessment.id,
            "assessment_pass": assessment.assessment_pass,
            "result": assessment.result,
            "rationale_preview": preview_text(assessment.rationale),
        },
    )


async def emit_completeness_persisted(
    session: AsyncSession,
    *,
    completeness: ResearchCompletenessPass,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=completeness.attempt_id,
        event_type="global_completeness_persisted",
        idempotency_key=f"completeness:{completeness.completeness_pass}",
        payload={
            "completeness_id": completeness.id,
            "completeness_pass": completeness.completeness_pass,
            "result": completeness.result,
            "rationale_preview": preview_text(completeness.rationale),
        },
    )


async def emit_capability_unavailable(
    session: AsyncSession,
    *,
    completeness: ResearchCompletenessPass,
) -> ResearchProgressEvent:
    unavailable: list[str] = []
    for raw in completeness.missing_questions or []:
        if not isinstance(raw, dict):
            continue
        for item in raw.get("unavailable_source_types") or []:
            if isinstance(item, str) and item not in unavailable:
                unavailable.append(item)
    return await append_research_progress_event(
        session,
        attempt_id=completeness.attempt_id,
        event_type="capability_unavailable",
        idempotency_key=f"capability_unavailable:{completeness.completeness_pass}",
        payload={
            "completeness_id": completeness.id,
            "completeness_pass": completeness.completeness_pass,
            "unavailable_source_types": unavailable,
        },
    )


async def emit_research_frozen_ready(
    session: AsyncSession,
    *,
    attempt_id: str,
    evidence_set_id: str | None,
    stop_reason: str | None,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=attempt_id,
        event_type="research_frozen_ready",
        idempotency_key="research_frozen_ready",
        payload={
            "evidence_set_id": evidence_set_id,
            "stop_reason": stop_reason,
        },
    )


async def emit_research_failed(
    session: AsyncSession,
    *,
    attempt_id: str,
    reason: str | None = None,
) -> ResearchProgressEvent:
    return await append_research_progress_event(
        session,
        attempt_id=attempt_id,
        event_type="research_failed",
        idempotency_key="research_failed",
        payload={"reason": reason} if reason else {},
    )
