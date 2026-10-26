"""Owner-backed knowledge mirrors for entities, relationships and observations."""

from __future__ import annotations

import json
from typing import Any

from app.services.knowledge.graph_entity_mirror import (
    ENTITY_NAMESPACE,
    graph_node_type,
    merged_attributes,
)
from app.services.knowledge.graph_relationship_mirror import (
    KIND_LABELS,
    LINKED,
    RELATION_LABELS,
    MirroredRelationship,
)
from app.services.overgraph.claims import (
    OBSERVATION_CLASS,
    VERIFICATION_OBSERVATION,
    VerificationObservationWrite,
    _statement,
)
from app.services.overgraph.labels import (
    DOCUMENT,
    ENTITY,
    scope_label,
)
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_graph import apply_batch, make_edge, make_node
from app.services.overgraph.write import entity_nodes


async def entity_exists(
    client: OwnerClient, *, scope_key: str, entity_id: str,
) -> bool:
    response = await client.read([{"label": ENTITY, "key": entity_id}])
    props = response["values"].get(f"{ENTITY}:{entity_id}") or {}
    return str(props.get("scope_key") or "") == scope_key


async def mirror_entity(client: OwnerClient, entity) -> str:
    """Write the SQL-parity entity node and identifier alias in one batch."""
    response = await client.read([{"label": ENTITY, "key": entity.id}])
    existing_props = response["values"].get(f"{ENTITY}:{entity.id}")
    existing = None if existing_props is None else GraphRecord(
        key=entity.id, labels=(ENTITY,), props=dict(existing_props),
    )
    from app.services.graph_v2.types import NodeInput

    proposed = NodeInput(
        node_type=graph_node_type(entity.entity_type),
        name=entity.name,
        scope=entity.scope,
        identifier_namespace=ENTITY_NAMESPACE,
        identifier=entity.key,
        attributes=merged_attributes(existing, entity),
    )
    _key, nodes = entity_nodes(proposed)
    payload = []
    for node in nodes:
        copy = {
            "labels": list(node["labels"]),
            "key": entity.id if node["key"] == _key else node["key"],
            "props": dict(node["props"]),
        }
        if copy["labels"] and "Identifier" in copy["labels"]:
            copy["props"]["node_key"] = entity.id
        payload.append(copy)
    await apply_batch(client, "knowledge:entity", nodes=payload, edges=[])
    return entity.id


async def observation_exists(client: OwnerClient, observation) -> bool:
    response = await client.read([
        {"label": VERIFICATION_OBSERVATION, "key": observation.id},
    ])
    return response["values"].get(
        f"{VERIFICATION_OBSERVATION}:{observation.id}",
    ) is not None


async def mirror_observation(client: OwnerClient, observation) -> str:
    write = VerificationObservationWrite(
        class_id=observation.observation_class,
        document_id=observation.document_id,
        document_version_id=observation.document_version_id,
        value={
            "statement": observation.statement_normalized,
            "question_key": observation.question_key,
        },
        polarity="observed",
        taxonomy_version="research-observation-v1",
        scope=observation.scope,
        kind=observation.kind,
        decision=None,
    )
    statement = _statement(write)
    props = {
        "scope_key": observation.scope.scope_key,
        "observation_class": OBSERVATION_CLASS,
        "kind": observation.kind,
        "class_id": observation.observation_class,
        "value": {
            "statement": observation.statement_normalized,
            "question_key": observation.question_key,
        },
        "polarity": "observed",
        "taxonomy_version": "research-observation-v1",
        "document_id": observation.document_id,
        "document_version_id": observation.document_version_id,
        "statement": statement,
        "source_unit_keys_json": json.dumps([], ensure_ascii=False, sort_keys=True),
    }
    await apply_batch(client, "knowledge:observation", nodes=[
        make_node(
            [VERIFICATION_OBSERVATION, scope_label(observation.scope.scope_key)],
            observation.id, props,
        )
    ], edges=[])
    return observation.id


async def _read_edge(client: OwnerClient, edge) -> dict[str, Any] | None:
    source_label = KIND_LABELS.get(edge.from_kind)
    target_label = KIND_LABELS.get(edge.to_kind)
    if source_label is None or target_label is None:
        return None
    response = await client.read([
        {"label": source_label, "key": edge.from_id},
        {"label": target_label, "key": edge.to_id},
    ])
    source_id = response["ids"].get(f"{source_label}:{edge.from_id}")
    target_key = edge.to_id
    if source_id is None or response["ids"].get(f"{target_label}:{target_key}") is None:
        return None
    label = RELATION_LABELS.get(edge.relation, LINKED)
    for row in await client.neighbors(
        int(source_id), direction="outgoing", labels=[label], limit=200,
    ):
        if str(row.get("key") or "") == target_key:
            return dict(row.get("edge_props") or {})
    return None


async def mirror_relationship(
    client: OwnerClient, edge,
) -> MirroredRelationship:
    from app.services.knowledge.relationships import merge_relationship_extra

    source_label = KIND_LABELS.get(edge.from_kind)
    target_label = KIND_LABELS.get(edge.to_kind)
    if source_label is None or target_label is None:
        return MirroredRelationship(key=edge.id, created=False, mappable=False)
    nodes = []
    for kind, document_id in ((edge.from_kind, edge.from_id), (edge.to_kind, edge.to_id)):
        if kind == "document":
            nodes.append(make_node(
                [DOCUMENT, scope_label(edge.scope.scope_key)], document_id,
                {"scope_key": edge.scope.scope_key, "document_id": document_id},
            ))
    response = await client.read([
        {"label": source_label, "key": edge.from_id},
        {"label": target_label, "key": edge.to_id},
    ])
    source_exists = (
        edge.from_kind == "document"
        or response["ids"].get(f"{source_label}:{edge.from_id}") is not None
    )
    target_exists = (
        edge.to_kind == "document"
        or response["ids"].get(f"{target_label}:{edge.to_id}") is not None
    )
    if not source_exists or not target_exists:
        return MirroredRelationship(key=edge.id, created=False, mappable=False)
    label = RELATION_LABELS.get(edge.relation, LINKED)
    existing = await _read_edge(client, edge)
    merged = merge_relationship_extra(existing.get("extra") if existing else None, edge.extra)
    await apply_batch(client, "knowledge:relationship", nodes=nodes, edges=[make_edge(
        (source_label, edge.from_id), (target_label, edge.to_id), label,
        {
            "relation": edge.relation,
            "extra": merged,
            "from_kind": edge.from_kind,
            "to_kind": edge.to_kind,
            "temporal_key": edge.temporal_key,
        },
    )])
    return MirroredRelationship(key=edge.id, created=existing is None)
