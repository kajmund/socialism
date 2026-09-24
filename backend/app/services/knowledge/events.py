"""Append-only knowledge graph events. Supersede; do not rewrite history."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeGraphEventRecord
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeTenantScope,
    persist_scope_fields,
    require_persist_scope,
    scope_from_row,
    visible_to_customer_clause,
)

CLAIM_ADDED = "CLAIM_ADDED"
EDGE_ADDED = "EDGE_ADDED"
CLAIM_SUPERSEDED = "CLAIM_SUPERSEDED"

GRAPH_EVENT_TYPES = frozenset({CLAIM_ADDED, EDGE_ADDED, CLAIM_SUPERSEDED})
GraphEventType = Literal["CLAIM_ADDED", "EDGE_ADDED", "CLAIM_SUPERSEDED"]


class KnowledgeGraphEventError(RuntimeError):
    """A graph event could not be recorded."""


@dataclass(frozen=True)
class KnowledgeGraphEvent:
    id: str
    customer_id: int | None
    event_type: GraphEventType
    node_kind: str
    node_id: str
    related_id: str | None
    payload: dict[str, object]
    created_at: datetime | None = None
    scope_type: str = SCOPE_CUSTOMER

    @property
    def scope(self) -> KnowledgeTenantScope:
        return require_persist_scope(scope_type=self.scope_type, customer_id=self.customer_id)


def graph_event_id(
    *,
    event_type: str,
    node_kind: str,
    node_id: str,
    related_id: str | None = None,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
) -> str:
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    payload = (
        f"{resolved.scope_key}\0{event_type}\0{node_kind}\0{node_id}\0{related_id or ''}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


async def record_graph_event(
    session: AsyncSession,
    *,
    event_type: GraphEventType,
    node_kind: str,
    node_id: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
    related_id: str | None = None,
    payload: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> KnowledgeGraphEventRecord:
    if event_type not in GRAPH_EVENT_TYPES:
        raise KnowledgeGraphEventError(f"unknown graph event type: {event_type}")
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    event_id = graph_event_id(
        scope=resolved,
        event_type=event_type,
        node_kind=node_kind,
        node_id=node_id,
        related_id=related_id,
    )
    existing = await session.get(KnowledgeGraphEventRecord, event_id)
    if existing is not None:
        if scope_from_row(existing) != resolved:
            raise KnowledgeGraphEventError(
                f"graph event {event_id} already exists in a different knowledge scope"
            )
        return existing
    row = KnowledgeGraphEventRecord(
        id=event_id,
        event_type=event_type,
        node_kind=node_kind,
        node_id=node_id,
        related_id=related_id,
        payload=dict(payload or {}),
        created_at=created_at or utc_now(),
        **persist_scope_fields(resolved),
    )
    session.add(row)
    await session.flush()
    return row


async def list_graph_events(
    session: AsyncSession,
    *,
    customer_id: int,
    node_kind: str | None = None,
    node_id: str | None = None,
) -> list[KnowledgeGraphEvent]:
    query = select(KnowledgeGraphEventRecord).where(
        visible_to_customer_clause(
            KnowledgeGraphEventRecord.scope_type,
            KnowledgeGraphEventRecord.customer_id,
            customer_id,
        )
    )
    if node_kind is not None:
        query = query.where(KnowledgeGraphEventRecord.node_kind == node_kind)
    if node_id is not None:
        query = query.where(KnowledgeGraphEventRecord.node_id == node_id)
    rows = (
        await session.execute(query.order_by(KnowledgeGraphEventRecord.created_at))
    ).scalars().all()
    events: list[KnowledgeGraphEvent] = []
    for row in rows:
        scope = scope_from_row(row)
        events.append(
            KnowledgeGraphEvent(
                id=row.id,
                customer_id=scope.customer_id,
                scope_type=scope.scope_type,
                event_type=row.event_type,  # type: ignore[arg-type]
                node_kind=row.node_kind,
                node_id=row.node_id,
                related_id=row.related_id,
                payload=dict(row.payload or {}),
                created_at=row.created_at,
            )
        )
    return events
