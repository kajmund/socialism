"""Typed knowledge edges. Core relations are closed; adapters namespace extras."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CanonicalDocumentRecord,
    KnowledgeRelationshipRecord,
)
from app.services.knowledge.claims import SUPPORTED_BY
from app.services.knowledge.events import EDGE_ADDED, record_graph_event, utc_now
from app.services.knowledge.graph_relationship_mirror import mirror_relationship
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    shared_scope,
    KnowledgeTenantScope,
    assert_relationship_scopes,
    require_persist_scope,
    scope_from_row,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import CONTRADICTS as GRAPH_CONTRADICTS
from app.services.overgraph.labels import (
    CLAIM,
    DOCUMENT,
    ENTITY,
    LINKED,
    SUPPORTS,
    TEXT_UNIT,
    visible_scope_keys,
)

from app.services.overgraph.research import load_text_units

_EDGE_LABELS = (SUPPORTS, GRAPH_CONTRADICTS, LINKED)
KIND_LABEL = {"entity": ENTITY, "claim": CLAIM, "text_unit": TEXT_UNIT,
              "document": DOCUMENT}

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
    temporal_key: str = ""

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
    scope: KnowledgeTenantScope,
    temporal_key: str = "",
) -> str:
    resolved = require_persist_scope(scope=scope)
    stamp = temporal_key.strip()
    if resolved.scope_type == SCOPE_CUSTOMER:
        payload = (
            f"{resolved.customer_id}\0{relation}\0{from_kind}\0{from_id}\0"
            f"{to_kind}\0{to_id}\0{stamp}"
        )
    else:
        payload = f"shared\0{relation}\0{from_kind}\0{from_id}\0{to_kind}\0{to_id}\0{stamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def knowledge_relationship(  # noqa: PLR0913
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
    payload = dict(extra or {})
    stamp = str(payload.pop("temporal_key", "") or "").strip()
    return KnowledgeRelationship(
        id=knowledge_relationship_id(
            scope=resolved,
            relation=rel,
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
            temporal_key=stamp,
        ),
        customer_id=resolved.customer_id,
        scope_type=resolved.scope_type,
        relation=rel,
        from_kind=from_kind,
        from_id=from_id,
        to_kind=to_kind,
        to_id=to_id,
        extra=payload,
        temporal_key=stamp,
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
    row, _reused = await persist_knowledge_relationship_result(session, edge)
    return row


@dataclass(frozen=True)
class PersistedRelationship:
    """Outcome of a relationship write. The graph edge is authoritative."""

    id: str


async def persist_knowledge_relationship_result(
    session: AsyncSession,
    edge: KnowledgeRelationship,
) -> tuple[KnowledgeRelationship, bool]:
    """Write the edge to OverGraph; the graph edge is authoritative."""
    await _assert_endpoint_scopes(session, edge)
    existing = await _existing_edge_in_graph(edge)
    if existing is not None:
        _reject_superseded_extra(existing)
    merged = await asyncio.to_thread(mirror_relationship, edge)
    if not merged.mappable:
        raise KnowledgeRelationshipError(
            f"relationship {edge.id} has an endpoint missing from the graph "
            f"({edge.from_kind}:{edge.from_id} -> {edge.to_kind}:{edge.to_id})"
        )
    if merged.created:
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
            created_at=utc_now(),
        )
    row = await asyncio.to_thread(_read_edge, edge)
    stored = replace(
        edge,
        id=row.props.get("relation_id") or edge.id if row is not None else edge.id,
        extra=dict(row.props.get("extra") or {}) if row is not None else dict(edge.extra or {}),
    )
    return stored, not merged.created


async def _existing_edge_in_graph(edge: KnowledgeRelationship):
    return await asyncio.to_thread(_read_edge, edge)


def _read_edge(edge: KnowledgeRelationship):
    from app.services.knowledge.graph_relationship_mirror import edge_in_graph

    return edge_in_graph(require_knowledge(), edge)


def _reject_superseded_extra(row) -> None:
    if bool(row.props.get("superseded")):
        raise KnowledgeRelationshipError("relationship is superseded")


def merge_relationship_extra(
    existing: dict[str, object] | None,
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(existing or {})
    for key, value in incoming.items():
        prior = merged.get(key)
        if isinstance(prior, list) and isinstance(value, list):
            seen: list[object] = []
            for item in [*prior, *value]:
                if item not in seen:
                    seen.append(item)
            merged[key] = seen
        else:
            merged[key] = value
    return merged


async def relationships_touching(
    session: AsyncSession,
    *,
    customer_id: int,
    kind: NodeKind,
    node_id: str,
) -> list[KnowledgeRelationship]:
    """Edges touching a node, read from OverGraph and filtered by tenant visibility."""
    catalog = require_knowledge()
    visible = {*visible_scope_keys(customer_id)}
    node = catalog.get_by_key(ENTITY if kind == "entity" else KIND_LABEL[kind], node_id)
    if node is None or node.engine_id is None:
        return []
    if str(node.props.get("scope_key") or "") not in visible:
        return []
    edges: list[KnowledgeRelationship] = []
    for direction in ("outgoing", "incoming"):
        for neighbour_id in catalog.neighbors(node.engine_id, direction=direction):
            neighbour = catalog.get(neighbour_id)
            if neighbour is None:
                continue
            scope_key = str(neighbour.props.get("scope_key") or "")
            if scope_key not in visible:
                continue
            source = node.engine_id if direction == "outgoing" else neighbour_id
            target = neighbour_id if direction == "outgoing" else node.engine_id
            for label in _EDGE_LABELS:
                edge = catalog.get_edge_by_triple(source, target, label)
                if edge is None:
                    continue
                edges.append(
                    KnowledgeRelationship(
                        id=f"{source}->{target}:{label}",
                        customer_id=customer_id,
                        relation=str(edge.props.get("relation") or label),
                        from_kind=kind,
                        from_id=node_id,
                        to_kind=kind,
                        to_id=str(neighbour.key),
                        extra=dict(edge.props.get("extra") or {}),
                    )
                )
    return edges


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
        temporal_key=row.temporal_key or "",
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


def entity_in_graph_scoped(node_id: str):
    """Entity node without a scope filter (caller compares scopes explicitly)."""
    from app.services.overgraph.labels import ENTITY

    catalog = require_knowledge()
    row = catalog.get_by_key(ENTITY, node_id)
    return row


def scope_from_props(props) -> KnowledgeTenantScope | None:
    scope_key = str(props.get("scope_key") or "")
    if not scope_key:
        return None
    if scope_key == "shared":
        return shared_scope()
    if scope_key.startswith("customer:"):
        return require_persist_scope(customer_id=int(scope_key.split(":", 1)[1]))
    return None


async def _endpoint_scope(
    session: AsyncSession,
    kind: str,
    node_id: str,
) -> KnowledgeTenantScope | None:
    if kind == "entity":
        node = entity_in_graph_scoped(node_id)
        return scope_from_props(node.props) if node is not None else None
    if kind == "claim":
        node = require_knowledge().get_by_key(CLAIM, node_id)
        return scope_from_props(node.props) if node is not None else None
    elif kind == "document":
        row = await session.get(CanonicalDocumentRecord, node_id)
    elif kind == "text_unit":
        catalog = require_knowledge()
        loaded = await catalog.run(load_text_units, catalog, [node_id])
        row = loaded[0] if loaded else None
    else:
        return None
    if row is None:
        return None
    return scope_from_row(row)
