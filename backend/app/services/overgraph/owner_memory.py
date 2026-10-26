"""Owner-backed memory catalog operations for expert memory.

The memory catalog keeps the existing mem0 node shape; this module is the
async Owner access path that replaces direct catalog reads and writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.services.overgraph.labels import (
    LINKED,
    MEMORY,
    MEMORY_ENTITY,
    agent_label,
    user_label,
)
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_graph import (
    GraphBatch,
    apply_batch,
    make_edge,
    make_node,
    neighbors_of,
    props_of,
    read_nodes,
)

PAGE_LIMIT = 200


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    score: float | None
    payload: dict[str, Any]
    vector: tuple[float, ...] | None = None


def _kind(collection_name: str) -> str:
    return MEMORY_ENTITY if collection_name.endswith("_entities") else MEMORY


def _labels(kind: str, payload: dict[str, Any]) -> list[str]:
    labels = [kind]
    user_id = str(payload.get("user_id") or "")
    agent_id = str(payload.get("agent_id") or "")
    if user_id:
        labels.append(user_label(user_id))
    if agent_id:
        labels.append(agent_label(agent_id))
    return labels


def _payload(props: dict[str, Any]) -> dict[str, Any]:
    return dict(json.loads(str(props.get("payload_json") or "{}")))


def _record(row: dict[str, Any], *, score: float | None = None) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["key"]), score=score, payload=_payload(dict(row.get("props") or {})),
    )


async def get(client: OwnerClient, kind: str, memory_id: str) -> MemoryRecord | None:
    response = await read_nodes(client, [(kind, memory_id)])
    props = props_of(response, kind, memory_id)
    if props is None:
        return None
    return _record({"key": memory_id, "props": props})


async def upsert(
    client: OwnerClient,
    *,
    kind: str,
    memory_id: str,
    vector: list[float] | None,
    payload: dict[str, Any],
    collection: str,
) -> None:
    linked = [str(item) for item in payload.get("linked_memory_ids") or ()]
    targets = await read_nodes(client, [(MEMORY, item) for item in linked])
    batch = GraphBatch(nodes=[make_node(_labels(kind, payload), memory_id, {
        "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "user_id": str(payload.get("user_id") or ""),
        "agent_id": str(payload.get("agent_id") or ""),
        "collection": collection,
    }, dense_vector=vector or None)])
    for item in linked:
        if props_of(targets, MEMORY, item) is not None:
            batch.edges.append(make_edge((kind, memory_id), (MEMORY, item), LINKED))
    await apply_batch(client, "memory:upsert", nodes=batch.nodes, edges=batch.edges)


async def update(
    client: OwnerClient,
    *,
    kind: str,
    memory_id: str,
    vector: list[float] | None = None,
    payload: dict[str, Any] | None = None,
    collection: str,
) -> None:
    response = await read_nodes(client, [(kind, memory_id)], include_vectors=True)
    props = props_of(response, kind, memory_id)
    merged = _payload(props or {})
    if payload:
        merged.update(payload)
    dense = vector
    if dense is None:
        dense = response.get("vectors", {}).get(f"{kind}:{memory_id}")
    await upsert(
        client, kind=kind, memory_id=memory_id, vector=dense, payload=merged,
        collection=collection,
    )


async def delete(client: OwnerClient, kind: str, memory_id: str) -> None:
    await apply_batch(
        client, "memory:delete", nodes=[], edges=[],
        deletes=[{"label": kind, "key": memory_id}],
    )


async def _linked_count(client: OwnerClient, kind: str, memory_id: str) -> int:
    response = await read_nodes(client, [(kind, memory_id)])
    node_id = response.get("ids", {}).get(f"{kind}:{memory_id}")
    if node_id is None:
        return 0
    return len(await neighbors_of(client, int(node_id), LINKED))


async def search(
    client: OwnerClient,
    *,
    kind: str,
    vector: list[float],
    top_k: int,
    filters: dict[str, Any] | None = None,
) -> list[MemoryRecord]:
    filters = filters or {}
    labels = [kind]
    if filters.get("user_id"):
        labels.append(user_label(str(filters["user_id"])))
    if filters.get("agent_id"):
        labels.append(agent_label(str(filters["agent_id"])))
    hits = await client.vector_search(labels, vector, k=top_k)
    records: list[MemoryRecord] = []
    for hit in hits:
        payload = _payload(dict(hit.get("props") or {}))
        if filters.get("user_id") and payload.get("user_id") != filters["user_id"]:
            continue
        if filters.get("agent_id") and payload.get("agent_id") != filters["agent_id"]:
            continue
        memory_id = str(hit["key"])
        linked = await _linked_count(client, kind, memory_id)
        if linked:
            payload = {**payload, "linked_count": linked}
        records.append(MemoryRecord(id=memory_id, score=float(hit["score"]), payload=payload))
    return records


async def list_records(
    client: OwnerClient,
    *,
    kind: str,
    filters: dict[str, Any] | None = None,
    limit: int = 10_000,
    include_vectors: bool = False,
) -> list[MemoryRecord]:
    filters = filters or {}
    props: dict[str, Any] = {}
    for name in ("user_id", "agent_id"):
        if filters.get(name):
            props[name] = str(filters[name])
    records: list[MemoryRecord] = []
    cursor: int | None = None
    while len(records) < limit:
        page = await client.query_nodes(
            kind, props=props, limit=min(PAGE_LIMIT, limit - len(records)),
            after=cursor, include_vectors=include_vectors,
        )
        for row in page["nodes"]:
            records.append(MemoryRecord(
                id=str(row["key"]), score=None, payload=_payload(dict(row.get("props") or {})),
                vector=tuple(row.get("dense_vector") or ()) or None,
            ))
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    return records


def memory_kind(collection_name: str) -> str:
    return _kind(collection_name)


async def apply_changes(
    client: OwnerClient,
    *,
    kind: str,
    collection: str,
    upserts: list[MemoryRecord],
    deletes: list[str],
) -> None:
    """Publish a staging diff for one memory collection in one owner batch."""
    batch = GraphBatch()
    for record in upserts:
        payload = dict(record.payload)
        batch.nodes.append(make_node(_labels(kind, payload), record.id, {
            "payload_json": json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"),
            ),
            "user_id": str(payload.get("user_id") or ""),
            "agent_id": str(payload.get("agent_id") or ""),
            "collection": collection,
        }, dense_vector=list(record.vector) if record.vector else None))
        for linked in payload.get("linked_memory_ids") or ():
            batch.edges.append(make_edge((kind, record.id), (MEMORY, str(linked)), LINKED))
    if upserts or deletes:
        await apply_batch(
            client, "memory:apply", nodes=batch.nodes, edges=batch.edges,
            deletes=[{"label": kind, "key": memory_id} for memory_id in deletes],
        )
