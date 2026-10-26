"""Domain-neutral named nodes. Adapters own entity_type strings."""

from __future__ import annotations




import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge import owner_graph_mirror
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeScopeError,
    KnowledgeTenantScope,
    require_persist_scope,
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


@dataclass(frozen=True)
class PersistedEntity:
    """Outcome of an entity write, without leaking the SQL model to callers."""

    id: str


async def persist_knowledge_entities(
    session: AsyncSession,
    entities: Sequence[KnowledgeEntity],
) -> list[KnowledgeEntity]:
    return [await persist_knowledge_entity(session, entity) for entity in entities]


async def persist_knowledge_entity(
    session: AsyncSession,
    entity: KnowledgeEntity,
) -> KnowledgeEntity:
    merged, _reused = await persist_knowledge_entity_result(session, entity)
    return merged


async def persist_knowledge_entity_result(
    session: AsyncSession,
    entity: KnowledgeEntity,
) -> tuple[KnowledgeEntity, bool]:
    """Write the node to OverGraph; identity is deterministic per scope/type/key."""
    owner = get_owner_runtime().require_client()
    if owner is not None:
        response = await owner.read([{"label": "Entity", "key": entity.id}])
        props = response["values"].get(f"Entity:{entity.id}")
        existing = None if props is None else type("Row", (), {"props": dict(props)})()
        if (
            existing is not None
            and str(existing.props.get("scope_key") or "") != entity.scope.scope_key
        ):
            raise KnowledgeEntityError(
                f"entity {entity.id} already exists in a different knowledge scope"
            )
        await owner_graph_mirror.mirror_entity(owner, entity)
        row_response = await owner.read([{"label": "Entity", "key": entity.id}])
        row_props = row_response["values"].get(f"Entity:{entity.id}")
        if row_props is None:
            raise KnowledgeEntityError(f"entity {entity.id} was not written to OverGraph")
        from app.services.overgraph.model import GraphRecord

        row = GraphRecord(key=entity.id, labels=("Entity",), props=dict(row_props))
        return _domain_from_graph(row, entity), existing is not None



def _domain_from_graph(row, entity: KnowledgeEntity) -> KnowledgeEntity:
    """The graph node is the truth after a merge; mirror exactly that."""
    extra = row.props.get("attributes_json")
    return KnowledgeEntity(
        id=entity.id,
        customer_id=entity.customer_id,
        entity_type=entity.entity_type,
        key=entity.key,
        name=str(row.props.get("name") or entity.name),
        extra=dict(json.loads(str(extra)) if extra else {}),
        scope_type=entity.scope_type,
    )


async def lookup_knowledge_entity(
    session: AsyncSession,
    *,
    entity_type: str,
    key: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
):
    """Same-scope identity only. Does not merge customer entities into shared."""
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    identity = knowledge_entity_id(scope=resolved, entity_type=entity_type, key=key)
    owner = get_owner_runtime().require_client()
    response = await owner.read([{"label": "Entity", "key": identity}])
    props = response["values"].get(f"Entity:{identity}")
    if props is None or str(props.get("scope_key") or "") != resolved.scope_key:
        return None
    from app.services.overgraph.model import GraphRecord

    return GraphRecord(
        key=identity, labels=("Entity",), props=dict(props),
        engine_id=response["ids"].get(f"Entity:{identity}"),
    )


async def lookup_readable_entity(
    session: AsyncSession,
    *,
    reader_customer_id: int,
    entity_type: str,
    key: str,
):
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
    if not visible_to(owned=shared_scope(), reader_customer_id=reader_customer_id):
        raise KnowledgeEntityError("shared entity was not readable")
    return shared


def _normalize_key(key: str) -> str:
    text = " ".join(key.casefold().split())
    if not text:
        raise KnowledgeEntityError("entity key is empty after normalize")
    return text
