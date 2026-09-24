"""Typed knowledge edges. Core relations are closed; adapters namespace extras."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeRelationshipRecord
from app.services.knowledge.claims import SUPPORTED_BY
from app.services.knowledge.events import EDGE_ADDED, record_graph_event, utc_now

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
    customer_id: int
    relation: str
    from_kind: NodeKind
    from_id: str
    to_kind: NodeKind
    to_id: str
    extra: dict[str, object]


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
    customer_id: int,
    relation: str,
    from_kind: str,
    from_id: str,
    to_kind: str,
    to_id: str,
) -> str:
    payload = f"{customer_id}\0{relation}\0{from_kind}\0{from_id}\0{to_kind}\0{to_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def knowledge_relationship(
    *,
    customer_id: int,
    relation: str,
    from_kind: NodeKind,
    from_id: str,
    to_kind: NodeKind,
    to_id: str,
    extra: dict[str, object] | None = None,
) -> KnowledgeRelationship:
    rel = require_relation(relation)
    if from_kind not in NODE_KINDS:
        raise KnowledgeRelationshipError(f"unknown from_kind: {from_kind}")
    if to_kind not in NODE_KINDS:
        raise KnowledgeRelationshipError(f"unknown to_kind: {to_kind}")
    if not from_id.strip() or not to_id.strip():
        raise KnowledgeRelationshipError("relationship endpoints require ids")
    return KnowledgeRelationship(
        id=knowledge_relationship_id(
            customer_id=customer_id,
            relation=rel,
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
        ),
        customer_id=customer_id,
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
    if row is None:
        now = utc_now()
        row = KnowledgeRelationshipRecord(
            id=edge.id,
            customer_id=edge.customer_id,
            relation=edge.relation,
            from_kind=edge.from_kind,
            from_id=edge.from_id,
            to_kind=edge.to_kind,
            to_id=edge.to_id,
            extra=edge.extra,
            valid_from=now,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        await record_graph_event(
            session,
            customer_id=edge.customer_id,
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
                KnowledgeRelationshipRecord.customer_id == customer_id,
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
    return KnowledgeRelationship(
        id=row.id,
        customer_id=row.customer_id,
        relation=row.relation,
        from_kind=row.from_kind,  # type: ignore[arg-type]
        from_id=row.from_id,
        to_kind=row.to_kind,  # type: ignore[arg-type]
        to_id=row.to_id,
        extra=dict(row.extra or {}),
    )
