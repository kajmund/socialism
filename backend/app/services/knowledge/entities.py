"""Domain-neutral named nodes. Adapters own entity_type strings."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeEntityRecord


class KnowledgeEntityError(RuntimeError):
    """An entity identity is invalid."""


@dataclass(frozen=True)
class KnowledgeEntity:
    id: str
    customer_id: int
    entity_type: str
    key: str
    name: str
    extra: dict[str, object]


def knowledge_entity_id(
    *,
    customer_id: int,
    entity_type: str,
    key: str,
) -> str:
    payload = f"{customer_id}\0{entity_type}\0{_normalize_key(key)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def knowledge_entity(
    *,
    customer_id: int,
    entity_type: str,
    key: str,
    name: str,
    extra: dict[str, object] | None = None,
) -> KnowledgeEntity:
    if not entity_type.strip():
        raise KnowledgeEntityError("entity_type is required")
    normalized_key = _normalize_key(key)
    display = name.strip()
    if not display:
        raise KnowledgeEntityError("entity name is required")
    return KnowledgeEntity(
        id=knowledge_entity_id(
            customer_id=customer_id,
            entity_type=entity_type,
            key=normalized_key,
        ),
        customer_id=customer_id,
        entity_type=entity_type.strip(),
        key=normalized_key,
        name=display,
        extra=dict(extra or {}),
    )


async def persist_knowledge_entities(
    session: AsyncSession,
    entities: Sequence[KnowledgeEntity],
) -> list[KnowledgeEntityRecord]:
    return [await persist_knowledge_entity(session, entity) for entity in entities]


async def persist_knowledge_entity(
    session: AsyncSession,
    entity: KnowledgeEntity,
) -> KnowledgeEntityRecord:
    row = await session.get(KnowledgeEntityRecord, entity.id)
    if row is None:
        row = KnowledgeEntityRecord(
            id=entity.id,
            customer_id=entity.customer_id,
            entity_type=entity.entity_type,
            entity_key=entity.key,
            name=entity.name,
            extra=entity.extra,
        )
        session.add(row)
        await session.flush()
        return row
    row.name = entity.name
    row.extra = entity.extra
    await session.flush()
    return row


def _normalize_key(key: str) -> str:
    text = " ".join(key.casefold().split())
    if not text:
        raise KnowledgeEntityError("entity key is empty after normalize")
    return text
