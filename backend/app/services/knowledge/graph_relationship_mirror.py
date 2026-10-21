"""Transitional mirror: legacy relationship rows also become OverGraph edges.

Only validated edges are mirrored (``SUPPORTS``, ``CONTRADICTS`` and generic ``LINKED``
with the relation name on the edge). Endpoints resolve to the mirrored claim/entity nodes;
edges touching TextUnits or documents keep their SQL row until parcel 5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dataclasses import dataclass

from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import (
    CLAIM,
    CONTRADICTS,
    DOCUMENT,
    ENTITY,
    LINKED,
    SUPPORTS,
    TEXT_UNIT,
    scope_label,
)

if TYPE_CHECKING:
    from app.services.knowledge.relationships import KnowledgeRelationship

KIND_LABELS = {"entity": ENTITY, "claim": CLAIM, "text_unit": TEXT_UNIT, "document": DOCUMENT}
RELATION_LABELS = {"SUPPORTED_BY": SUPPORTS, "CONTRADICTS": CONTRADICTS}


def _ensure_document_anchor(catalog, edge: KnowledgeRelationship) -> None:
    """Graph holds the adjacency anchor only; document metadata and ownership stay in SQL."""
    for kind, document_id in ((edge.from_kind, edge.from_id), (edge.to_kind, edge.to_id)):
        if kind != "document":
            continue
        catalog.upsert_node(
            [DOCUMENT, scope_label(edge.scope.scope_key)],
            document_id,
            props={"scope_key": edge.scope.scope_key, "document_id": document_id},
        )


@dataclass(frozen=True)
class MirroredRelationship:
    """Outcome of a relationship write.

    ``mappable`` is false when an endpoint has no graph representation yet (TextUnits and
    documents); such edges keep their SQL row until parcel 6.
    """

    key: str
    created: bool
    mappable: bool = True


def mirror_relationship(edge: KnowledgeRelationship) -> MirroredRelationship:
    """Write the graph edge, merging ``extra`` into an existing edge instead of replacing it."""
    source_label = KIND_LABELS.get(edge.from_kind)
    target_label = KIND_LABELS.get(edge.to_kind)
    if source_label is None or target_label is None:
        return MirroredRelationship(key=edge.id, created=False, mappable=False)
    catalog = require_knowledge()
    if edge.from_kind == "document" or edge.to_kind == "document":
        _ensure_document_anchor(catalog, edge)
    source = catalog.get_by_key(source_label, edge.from_id)
    target = catalog.get_by_key(target_label, edge.to_id)
    if source is None or target is None or source.engine_id is None or target.engine_id is None:
        return MirroredRelationship(key=edge.id, created=False, mappable=False)
    label = RELATION_LABELS.get(edge.relation, LINKED)
    existing = catalog.get_edge_by_triple(source.engine_id, target.engine_id, label)
    merged = dict(existing.props.get("extra") or {}) if existing is not None else {}
    merged.update(edge.extra or {})
    created = existing is None
    catalog.upsert_edge(
        source.engine_id,
        target.engine_id,
        label,
        props={
            "relation": edge.relation,
            "extra": merged,
            "from_kind": edge.from_kind,
            "to_kind": edge.to_kind,
            "temporal_key": edge.temporal_key,
        },
    )
    return MirroredRelationship(key=edge.id, created=created)


def edge_in_graph(catalog, edge):
    """The graph edge for this exact triple, with its stored properties."""
    source_label = KIND_LABELS.get(edge.from_kind)
    target_label = KIND_LABELS.get(edge.to_kind)
    if source_label is None or target_label is None:
        return None
    source = catalog.get_by_key(source_label, edge.from_id)
    target = catalog.get_by_key(target_label, edge.to_id)
    if source is None or target is None:
        return None
    label = RELATION_LABELS.get(edge.relation, LINKED)
    return catalog.get_edge_by_triple(source.engine_id, target.engine_id, label)
