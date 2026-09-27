"""Domain-neutral named nodes. Adapters own entity_type strings."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeEntityRecord
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeScopeError,
    KnowledgeTenantScope,
    persist_scope_fields,
    require_persist_scope,
    scope_from_row,
    shared_scope,
    visible_to,
)


class KnowledgeEntityError(RuntimeError):
    """An entity identity is invalid."""


@dataclass(frozen=True)
class KnowledgeEntity:
    id: str
    customer_id: int | None
    entity_type: str
    key: str
    name: str
    extra: dict[str, object]
    scope_type: str = SCOPE_CUSTOMER

    @property
    def scope(self) -> KnowledgeTenantScope:
        return require_persist_scope(scope_type=self.scope_type, customer_id=self.customer_id)


def knowledge_entity_id(
    *,
    entity_type: str,
    key: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
) -> str:
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    if resolved.scope_type == SCOPE_CUSTOMER:
        payload = f"{resolved.customer_id}\0{entity_type}\0{_normalize_key(key)}"
    else:
        payload = f"shared\0{entity_type}\0{_normalize_key(key)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def knowledge_entity(
    *,
    entity_type: str,
    key: str,
    name: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
    extra: dict[str, object] | None = None,
) -> KnowledgeEntity:
    if not entity_type.strip():
        raise KnowledgeEntityError("entity_type is required")
    normalized_key = _normalize_key(key)
    display = name.strip()
    if not display:
        raise KnowledgeEntityError("entity name is required")
    try:
        resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    except KnowledgeScopeError as exc:
        raise KnowledgeEntityError(str(exc)) from exc
    return KnowledgeEntity(
        id=knowledge_entity_id(
            scope=resolved,
            entity_type=entity_type,
            key=normalized_key,
        ),
        customer_id=resolved.customer_id,
        scope_type=resolved.scope_type,
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
    if row is not None:
        return await _update_entity(session, row, entity)
    row = KnowledgeEntityRecord(
        id=entity.id,
        entity_type=entity.entity_type,
        entity_key=entity.key,
        name=entity.name,
        extra=entity.extra,
        **persist_scope_fields(entity.scope),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        # Another need inserted this shared identity and committed while we waited.
        winner = await session.get(KnowledgeEntityRecord, entity.id)
        if winner is None:
            raise
        return await _update_entity(session, winner, entity)
    return row


async def _update_entity(
    session: AsyncSession,
    row: KnowledgeEntityRecord,
    entity: KnowledgeEntity,
) -> KnowledgeEntityRecord:
    if scope_from_row(row) != entity.scope:
        raise KnowledgeEntityError(
            f"entity {entity.id} already exists in a different knowledge scope"
        )
    row.name = entity.name
    row.extra = entity.extra
    await session.flush()
    return row


async def lookup_knowledge_entity(
    session: AsyncSession,
    *,
    entity_type: str,
    key: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
) -> KnowledgeEntityRecord | None:
    """Same-scope identity only. Does not merge customer entities into shared."""
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    return await session.get(
        KnowledgeEntityRecord,
        knowledge_entity_id(scope=resolved, entity_type=entity_type, key=key),
    )


async def lookup_readable_entity(
    session: AsyncSession,
    *,
    reader_customer_id: int,
    entity_type: str,
    key: str,
) -> KnowledgeEntityRecord | None:
    """Customer entity first, then shared. Never another tenant. Never merges."""
    owned = await lookup_knowledge_entity(
        session,
        customer_id=reader_customer_id,
        entity_type=entity_type,
        key=key,
    )
    if owned is not None:
        return owned
    shared = await lookup_knowledge_entity(
        session,
        scope=shared_scope(),
        entity_type=entity_type,
        key=key,
    )
    if shared is None:
        return None
    if not visible_to(owned=scope_from_row(shared), reader_customer_id=reader_customer_id):
        raise KnowledgeEntityError("shared entity was not readable")
    return shared


def _normalize_key(key: str) -> str:
    text = " ".join(key.casefold().split())
    if not text:
        raise KnowledgeEntityError("entity key is empty after normalize")
    return text
