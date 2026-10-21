"""Transitional mirror: a legacy SQL entity write also populates the OverGraph node.

The node key equals the SQL entity id, so both stores can be compared by identity while
the SQL write path is still authoritative (parcel 4) and removed in parcel 5.
"""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from app.services.graph_v2.types import NodeInput
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.write import upsert_entity_at_key

if TYPE_CHECKING:
    from app.services.knowledge.entities import KnowledgeEntity

ENTITY_NAMESPACE = "knowledge.entity"


def graph_node_type(entity_type: str) -> str:
    """OverGraph requires namespaced node types; legacy adapters may use bare names.

    Production adapters already use namespaced types (``legal.source``). A bare type is
    mapped deterministically instead of being rejected, so every mirrored entity has a
    valid, stable graph label.
    """
    return entity_type if "." in entity_type.strip() else f"{ENTITY_NAMESPACE}.{entity_type.strip()}"


def merged_attributes(existing, entity: KnowledgeEntity) -> dict[str, object]:
    """Same semantics as the SQL ``_update_entity``: merge extra, refresh the name."""
    raw = str(existing.props.get("attributes_json") or "{}") if existing is not None else "{}"
    merged = dict(json.loads(raw))
    merged.update(dict(entity.extra or {}))
    return merged


def entity_in_graph(catalog, *, scope_key: str, entity_id: str):
    """The mirrored entity node, restricted to the requested scope."""
    from app.services.overgraph.labels import ENTITY

    row = catalog.get_by_key(ENTITY, entity_id)
    if row is None or str(row.props.get("scope_key") or "") != scope_key:
        return None
    return row


def mirror_entity(entity: KnowledgeEntity) -> str:
    catalog = require_knowledge()
    existing = catalog.get_by_key("Entity", entity.id)
    node = upsert_entity_at_key(
        catalog,
        NodeInput(
            node_type=graph_node_type(entity.entity_type),
            name=entity.name,
            scope=entity.scope,
            identifier_namespace=ENTITY_NAMESPACE,
            identifier=entity.key,
            attributes=merged_attributes(existing, entity),
        ),
        entity.id,
    )
    return node.key
