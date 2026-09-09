"""Service operations for ExecutionRun → ExecutionAttempt → EvidenceSet."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionRun,
    Kund,
)
from app.services.execution.errors import (
    ExecutionError,
    ExecutionFrozenError,
    ExecutionImmutableError,
    ExecutionNotFoundError,
    ExecutionScopeError,
    ExecutionStatusError,
)
from app.services.execution.models import (
    ALLOWED_ATTEMPT_TRANSITIONS,
    ATTEMPT_STATUSES,
    PREPARATION_STATUSES,
    SNAPSHOT_LOCKED_STATUSES,
    AttemptStatus,
    EvidenceSetStatus,
)
from app.services.execution.snapshots import (
    EvidenceItemSnapshot,
    compute_content_hash,
    require_json_object,
    snapshot_research_evidence,
)
from app.services.research.models import ResearchEvidence


def new_id() -> str:
    return uuid4().hex


def utc_now() -> datetime:
    return datetime.now(UTC)


def _require_status(value: str) -> AttemptStatus:
    if value not in ATTEMPT_STATUSES:
        raise ExecutionStatusError(f"Unknown attempt status: {value}")
    return value  # type: ignore[return-value]


def _require_non_empty(value: str, *, field: str) -> str:
    text = value.strip()
    if not text:
        raise ExecutionError(f"{field} is required")
    return text


async def _require_customer(session: AsyncSession, customer_id: int) -> Kund:
    kund = await session.get(Kund, customer_id)
    if kund is None:
        raise ExecutionNotFoundError("customer", str(customer_id))
    return kund


async def get_run(session: AsyncSession, run_id: str) -> ExecutionRun:
    run = await session.get(ExecutionRun, run_id)
    if run is None:
        raise ExecutionNotFoundError("run", run_id)
    return run


async def get_attempt(session: AsyncSession, attempt_id: str) -> ExecutionAttempt:
    attempt = await session.get(ExecutionAttempt, attempt_id)
    if attempt is None:
        raise ExecutionNotFoundError("attempt", attempt_id)
    return attempt


async def get_evidence_set(session: AsyncSession, evidence_set_id: str) -> EvidenceSet:
    row = await session.get(
        EvidenceSet,
        evidence_set_id,
        options=(selectinload(EvidenceSet.items),),
    )
    if row is None:
        raise ExecutionNotFoundError("evidence_set", evidence_set_id)
    return row


async def list_evidence_items(
    session: AsyncSession, evidence_set_id: str
) -> list[EvidenceSetItem]:
    await get_evidence_set(session, evidence_set_id)
    result = await session.execute(
        select(EvidenceSetItem)
        .where(EvidenceSetItem.evidence_set_id == evidence_set_id)
        .order_by(EvidenceSetItem.retrieved_at, EvidenceSetItem.id)
    )
    return list(result.scalars().all())


async def create_run(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
    title: str,
    context: dict[str, object] | None = None,
) -> ExecutionRun:
    await _require_customer(session, customer_id)
    run = ExecutionRun(
        id=new_id(),
        customer_id=customer_id,
        module=_require_non_empty(module, field="module"),
        title=_require_non_empty(title, field="title"),
        context=require_json_object(context or {}, field="context"),
    )
    session.add(run)
    await session.flush()
    return run


async def create_evidence_set(
    session: AsyncSession,
    *,
    run_id: str,
    created_from_attempt_id: str | None = None,
) -> EvidenceSet:
    run = await get_run(session, run_id)
    if created_from_attempt_id is not None:
        attempt = await get_attempt(session, created_from_attempt_id)
        if attempt.run_id != run.id:
            raise ExecutionScopeError(
                "created_from_attempt_id must belong to the same run as the EvidenceSet"
            )
    row = EvidenceSet(
        id=new_id(),
        run_id=run.id,
        created_from_attempt_id=created_from_attempt_id,
        status="building",
    )
    session.add(row)
    await session.flush()
    return row


def _assert_building(evidence_set: EvidenceSet) -> None:
    if evidence_set.status != "building":
        raise ExecutionFrozenError(
            f"EvidenceSet {evidence_set.id} is {evidence_set.status} and cannot be mutated"
        )


async def add_evidence_items(
    session: AsyncSession,
    *,
    evidence_set_id: str,
    items: list[EvidenceItemSnapshot | ResearchEvidence],
) -> list[EvidenceSetItem]:
    evidence_set = await get_evidence_set(session, evidence_set_id)
    _assert_building(evidence_set)
    stored: list[EvidenceSetItem] = []
    for raw in items:
        snapshot = (
            raw
            if isinstance(raw, EvidenceItemSnapshot)
            else snapshot_research_evidence(raw)
        )
        provenance = require_json_object(snapshot.provenance, field="provenance")
        row = EvidenceSetItem(
            id=new_id(),
            evidence_set_id=evidence_set.id,
            research_need_id=snapshot.research_need_id,
            source_type=_require_non_empty(snapshot.source_type, field="source_type"),
            status=_require_non_empty(snapshot.status, field="status"),
            title=snapshot.title,
            excerpt=snapshot.excerpt,
            locator=snapshot.locator,
            source_id=snapshot.source_id,
            source_url=snapshot.source_url,
            provider=snapshot.provider,
            score=snapshot.score,
            provenance=provenance,
            retrieved_at=snapshot.retrieved_at,
            content_hash=compute_content_hash(
                title=snapshot.title,
                excerpt=snapshot.excerpt,
                locator=snapshot.locator,
                source_id=snapshot.source_id,
                source_url=snapshot.source_url,
                provenance=provenance,
            ),
        )
        session.add(row)
        stored.append(row)
    await session.flush()
    return stored


async def freeze_evidence_set(session: AsyncSession, evidence_set_id: str) -> EvidenceSet:
    evidence_set = await get_evidence_set(session, evidence_set_id)
    _assert_building(evidence_set)
    evidence_set.status = "frozen"
    evidence_set.frozen_at = utc_now()
    await session.flush()
    return evidence_set


async def _load_evidence_set_for_run(
    session: AsyncSession,
    *,
    evidence_set_id: str,
    run: ExecutionRun,
) -> EvidenceSet:
    evidence_set = await get_evidence_set(session, evidence_set_id)
    if evidence_set.run_id != run.id:
        raise ExecutionScopeError(
            "Attempt may only attach an EvidenceSet from the same run"
        )
    evidence_run = await get_run(session, evidence_set.run_id)
    if evidence_run.customer_id != run.customer_id:
        raise ExecutionScopeError(
            "Attempt may not attach an EvidenceSet owned by another customer"
        )
    return evidence_set


def _assert_snapshots_mutable(attempt: ExecutionAttempt) -> None:
    status = _require_status(attempt.status)
    if status in SNAPSHOT_LOCKED_STATUSES:
        raise ExecutionImmutableError(
            f"Attempt {attempt.id} snapshots are immutable after status={status}"
        )


def _assert_preparation(attempt: ExecutionAttempt, *, action: str) -> None:
    status = _require_status(attempt.status)
    if status not in PREPARATION_STATUSES:
        raise ExecutionImmutableError(
            f"Cannot {action} on attempt {attempt.id} with status={status}"
        )


async def create_attempt(
    session: AsyncSession,
    *,
    run_id: str,
    attempt_type: str,
    configuration_snapshot: dict[str, object] | None = None,
    input_snapshot: dict[str, object] | None = None,
    evidence_set_id: str | None = None,
    parent_attempt_id: str | None = None,
) -> ExecutionAttempt:
    run = await get_run(session, run_id)
    if parent_attempt_id is not None:
        parent = await get_attempt(session, parent_attempt_id)
        if parent.run_id != run.id:
            raise ExecutionScopeError("parent_attempt_id must belong to the same run")
    attached_id: str | None = None
    if evidence_set_id is not None:
        evidence_set = await _load_evidence_set_for_run(
            session, evidence_set_id=evidence_set_id, run=run
        )
        attached_id = evidence_set.id
    attempt = ExecutionAttempt(
        id=new_id(),
        run_id=run.id,
        parent_attempt_id=parent_attempt_id,
        attempt_type=_require_non_empty(attempt_type, field="attempt_type"),
        status="created",
        configuration_snapshot=require_json_object(
            configuration_snapshot or {}, field="configuration_snapshot"
        ),
        input_snapshot=require_json_object(input_snapshot or {}, field="input_snapshot"),
        evidence_set_id=attached_id,
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def attach_evidence_set(
    session: AsyncSession,
    *,
    attempt_id: str,
    evidence_set_id: str,
) -> ExecutionAttempt:
    attempt = await get_attempt(session, attempt_id)
    _assert_preparation(attempt, action="attach evidence")
    run = await get_run(session, attempt.run_id)
    evidence_set = await _load_evidence_set_for_run(
        session, evidence_set_id=evidence_set_id, run=run
    )
    attempt.evidence_set_id = evidence_set.id
    await session.flush()
    return attempt


async def set_attempt_snapshots(
    session: AsyncSession,
    *,
    attempt_id: str,
    configuration_snapshot: dict[str, object] | None = None,
    input_snapshot: dict[str, object] | None = None,
) -> ExecutionAttempt:
    attempt = await get_attempt(session, attempt_id)
    _assert_snapshots_mutable(attempt)
    if configuration_snapshot is not None:
        attempt.configuration_snapshot = require_json_object(
            configuration_snapshot, field="configuration_snapshot"
        )
    if input_snapshot is not None:
        attempt.input_snapshot = require_json_object(
            input_snapshot, field="input_snapshot"
        )
    await session.flush()
    return attempt


def _assert_evidence_ready_for_execution(evidence_set: EvidenceSet | None) -> None:
    if evidence_set is None:
        return
    status: EvidenceSetStatus | str = evidence_set.status
    if status != "frozen":
        raise ExecutionStatusError(
            f"EvidenceSet {evidence_set.id} must be frozen before the attempt leaves preparation"
        )


async def transition_attempt(
    session: AsyncSession,
    *,
    attempt_id: str,
    status: AttemptStatus,
) -> ExecutionAttempt:
    attempt = await get_attempt(session, attempt_id)
    current = _require_status(attempt.status)
    target = _require_status(status)
    if target not in ALLOWED_ATTEMPT_TRANSITIONS[current]:
        raise ExecutionStatusError(
            f"Cannot transition attempt {attempt.id} from {current} to {target}"
        )
    if target in SNAPSHOT_LOCKED_STATUSES and attempt.evidence_set_id is not None:
        evidence_set = await get_evidence_set(session, attempt.evidence_set_id)
        _assert_evidence_ready_for_execution(evidence_set)
    now = utc_now()
    if target == "running" and attempt.started_at is None:
        attempt.started_at = now
    if target in {"completed", "failed"} and attempt.completed_at is None:
        attempt.completed_at = now
        if attempt.started_at is None:
            attempt.started_at = now
    attempt.status = target
    await session.flush()
    return attempt


async def mark_researching(session: AsyncSession, attempt_id: str) -> ExecutionAttempt:
    return await transition_attempt(session, attempt_id=attempt_id, status="researching")


async def mark_ready(session: AsyncSession, attempt_id: str) -> ExecutionAttempt:
    return await transition_attempt(session, attempt_id=attempt_id, status="ready")


async def start_attempt(session: AsyncSession, attempt_id: str) -> ExecutionAttempt:
    return await transition_attempt(session, attempt_id=attempt_id, status="running")


async def complete_attempt(session: AsyncSession, attempt_id: str) -> ExecutionAttempt:
    return await transition_attempt(session, attempt_id=attempt_id, status="completed")


async def fail_attempt(session: AsyncSession, attempt_id: str) -> ExecutionAttempt:
    return await transition_attempt(session, attempt_id=attempt_id, status="failed")


async def clone_attempt(
    session: AsyncSession,
    source_attempt_id: str,
    *,
    configuration_override: dict[str, object] | None = None,
    attempt_type: str | None = None,
) -> ExecutionAttempt:
    """Create a new Attempt from an existing one. Does not mutate the source."""
    source = await get_attempt(session, source_attempt_id)
    source_config = deepcopy(source.configuration_snapshot)
    source_input = deepcopy(source.input_snapshot)
    source_status = source.status
    source_started = source.started_at
    source_completed = source.completed_at
    source_evidence_id = source.evidence_set_id
    source_type = source.attempt_type

    reused_evidence_id: str | None = None
    if source.evidence_set_id is not None:
        evidence_set = await get_evidence_set(session, source.evidence_set_id)
        if evidence_set.status == "frozen":
            reused_evidence_id = evidence_set.id

    merged = deepcopy(source.configuration_snapshot)
    if configuration_override is not None:
        merged.update(require_json_object(configuration_override, field="configuration_override"))

    clone = await create_attempt(
        session,
        run_id=source.run_id,
        attempt_type=attempt_type or source.attempt_type,
        configuration_snapshot=merged,
        input_snapshot=deepcopy(source.input_snapshot),
        evidence_set_id=reused_evidence_id,
        parent_attempt_id=source.id,
    )

    reloaded = await get_attempt(session, source.id)
    if (
        reloaded.configuration_snapshot != source_config
        or reloaded.input_snapshot != source_input
        or reloaded.status != source_status
        or reloaded.started_at != source_started
        or reloaded.completed_at != source_completed
        or reloaded.evidence_set_id != source_evidence_id
        or reloaded.attempt_type != source_type
        or reloaded.parent_attempt_id != source.parent_attempt_id
    ):
        raise ExecutionError("clone_attempt must not mutate the source attempt")
    return clone
