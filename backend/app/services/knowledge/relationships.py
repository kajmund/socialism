"""Typed knowledge edges. Core relations are closed; adapters namespace extras."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CanonicalDocumentRecord,
    KnowledgeClaimRecord,
    KnowledgeEntityRecord,
    KnowledgeRelationshipRecord,
    TextUnitRecord,
)
from app.services.knowledge.claims import SUPPORTED_BY
from app.services.knowledge.events import EDGE_ADDED, record_graph_event, utc_now
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeTenantScope,
    assert_relationship_scopes,
    persist_scope_fields,
    require_persist_scope,
    scope_from_row,
    visible_to_customer_clause,
)

ABOUT = "ABOUT"
CONTRADICTS = "CONTRADICTS"
PART_OF = "PART_OF"
SAME_AS = "SAME_AS"

CORE_RELATIONS = frozenset({ABOUT, SUPPORTED_BY, CONTRADICTS, PART_OF, SAME_AS})
NODE_KINDS = frozenset({"entity", "claim", "text_unit", "document"})
NodeKind = Literal["entity", "claim", "text_unit", "document"]


class KnowledgeRelationshipError(RuntimeError):
    """A relationship cannot be stored."""


@dataclass(frozen=True)
class KnowledgeRelationship:
    id: str
    customer_id: int | None
    relation: str
    from_kind: NodeKind
    from_id: str
    to_kind: NodeKind
    to_id: str
    extra: dict[str, object]
    scope_type: str = SCOPE_CUSTOMER

    @property
    def scope(self) -> KnowledgeTenantScope:
        return require_persist_scope(scope_type=self.scope_type, customer_id=self.customer_id)


def require_relation(relation: str) -> str:
    text = relation.strip()
    if text in CORE_RELATIONS:
        return text
    if "." in text and text == relation:
        return text
    raise KnowledgeRelationshipError(
        f"unknown relation {relation!r}; use a core relation or a namespaced adapter relation"
    )


def knowledge_relationship_id(
    *,
    relation: str,
    from_kind: str,
    from_id: str,
    to_kind: str,
    to_id: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
) -> str:
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    if resolved.scope_type == SCOPE_CUSTOMER:
        payload = (
            f"{resolved.customer_id}\0{relation}\0{from_kind}\0{from_id}\0{to_kind}\0{to_id}"
        )
    else:
        payload = f"shared\0{relation}\0{from_kind}\0{from_id}\0{to_kind}\0{to_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def knowledge_relationship(
    *,
    relation: str,
    from_kind: NodeKind,
    from_id: str,
    to_kind: NodeKind,
    to_id: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
    extra: dict[str, object] | None = None,
) -> KnowledgeRelationship:
    rel = require_relation(relation)
    if from_kind not in NODE_KINDS:
        raise KnowledgeRelationshipError(f"unknown from_kind: {from_kind}")
    if to_kind not in NODE_KINDS:
        raise KnowledgeRelationshipError(f"unknown to_kind: {to_kind}")
    if not from_id.strip() or not to_id.strip():
        raise KnowledgeRelationshipError("relationship endpoints require ids")
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    return KnowledgeRelationship(
        id=knowledge_relationship_id(
            scope=resolved,
            relation=rel,
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
        ),
        customer_id=resolved.customer_id,
        scope_type=resolved.scope_type,
        relation=rel,
        from_kind=from_kind,
        from_id=from_id,
        to_kind=to_kind,
        to_id=to_id,
        extra=dict(extra or {}),
    )


async def persist_knowledge_relationships(
    session: AsyncSession,
    relationships: Sequence[KnowledgeRelationship],
) -> list[KnowledgeRelationshipRecord]:
    return [
        await persist_knowledge_relationship(session, edge) for edge in relationships
    ]


async def persist_knowledge_relationship(
    session: AsyncSession,
    edge: KnowledgeRelationship,
) -> KnowledgeRelationshipRecord:
    row = await session.get(KnowledgeRelationshipRecord, edge.id)
    await _assert_endpoint_scopes(session, edge)
    if row is not None:
        return await _update_relationship(session, row, edge)
    now = utc_now()
    row = KnowledgeRelationshipRecord(
        id=edge.id,
        relation=edge.relation,
        from_kind=edge.from_kind,
        from_id=edge.from_id,
        to_kind=edge.to_kind,
        to_id=edge.to_id,
        extra=edge.extra,
        valid_from=now,
        created_at=now,
        **persist_scope_fields(edge.scope),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        # Another need inserted this shared edge and committed while we waited.
        winner = await session.get(KnowledgeRelationshipRecord, edge.id)
        if winner is None:
            raise
        return await _update_relationship(session, winner, edge)
    await record_graph_event(
        session,
        scope=edge.scope,
        event_type=EDGE_ADDED,
        node_kind="relationship",
        node_id=edge.id,
        related_id=edge.to_id,
        payload={
            "relation": edge.relation,
            "from_kind": edge.from_kind,
            "from_id": edge.from_id,
            "to_kind": edge.to_kind,
            "to_id": edge.to_id,
        },
        created_at=now,
    )
    return row


async def _update_relationship(
    session: AsyncSession,
    row: KnowledgeRelationshipRecord,
    edge: KnowledgeRelationship,
) -> KnowledgeRelationshipRecord:
    if scope_from_row(row) != edge.scope:
        raise KnowledgeRelationshipError(
            f"relationship {edge.id} already exists in a different knowledge scope"
        )
    if row.superseded_at is not None:
        raise KnowledgeRelationshipError(f"relationship {edge.id} is superseded")
    row.extra = edge.extra
    await session.flush()
    return row


async def relationships_touching(
    session: AsyncSession,
    *,
    customer_id: int,
    kind: NodeKind,
    node_id: str,
) -> list[KnowledgeRelationship]:
    rows = (
        await session.execute(
            select(KnowledgeRelationshipRecord)
            .where(
                visible_to_customer_clause(
                    KnowledgeRelationshipRecord.scope_type,
                    KnowledgeRelationshipRecord.customer_id,
                    customer_id,
                ),
                KnowledgeRelationshipRecord.superseded_at.is_(None),
                or_(
                    (
                        (KnowledgeRelationshipRecord.from_kind == kind)
                        & (KnowledgeRelationshipRecord.from_id == node_id)
                    ),
                    (
                        (KnowledgeRelationshipRecord.to_kind == kind)
                        & (KnowledgeRelationshipRecord.to_id == node_id)
                    ),
                ),
            )
            .order_by(
                KnowledgeRelationshipRecord.relation,
                KnowledgeRelationshipRecord.id,
            )
        )
    ).scalars().all()
    return [_relationship_from_row(row) for row in rows]


def _relationship_from_row(row: KnowledgeRelationshipRecord) -> KnowledgeRelationship:
    scope = scope_from_row(row)
    return KnowledgeRelationship(
        id=row.id,
        customer_id=scope.customer_id,
        scope_type=scope.scope_type,
        relation=row.relation,
        from_kind=row.from_kind,  # type: ignore[arg-type]
        from_id=row.from_id,
        to_kind=row.to_kind,  # type: ignore[arg-type]
        to_id=row.to_id,
        extra=dict(row.extra or {}),
    )


async def _assert_endpoint_scopes(
    session: AsyncSession,
    edge: KnowledgeRelationship,
) -> None:
    from_scope = await _endpoint_scope(session, edge.from_kind, edge.from_id)
    to_scope = await _endpoint_scope(session, edge.to_kind, edge.to_id)
    try:
        assert_relationship_scopes(
            edge=edge.scope,
            from_scope=from_scope,
            to_scope=to_scope,
            relation=edge.relation,
        )
    except ValueError as exc:
        raise KnowledgeRelationshipError(str(exc)) from exc


async def _endpoint_scope(
    session: AsyncSession,
    kind: str,
    node_id: str,
) -> KnowledgeTenantScope | None:
    if kind == "entity":
        row = await session.get(KnowledgeEntityRecord, node_id)
    elif kind == "claim":
        row = await session.get(KnowledgeClaimRecord, node_id)
    elif kind == "document":
        row = await session.get(CanonicalDocumentRecord, node_id)
    elif kind == "text_unit":
        row = await session.get(TextUnitRecord, node_id)
    else:
        return None
    if row is None:
        return None
    return scope_from_row(row)
