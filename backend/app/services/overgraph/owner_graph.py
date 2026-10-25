"""Shared bounded batch/read helpers for Owner-backed repositories."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.services.overgraph.owner import OwnerClient

READ_LIMIT = 200


class OwnerGraphError(RuntimeError):
    """Owner rejected or lost a graph write."""


@dataclass
class GraphBatch:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


def _mutation_id(prefix: str, patch: dict[str, Any]) -> str:
    canonical = json.dumps(patch, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"


def make_node(
    label: str | list[str],
    key: str,
    props: dict[str, Any],
    *,
    dense_vector: list[float] | None = None,
) -> dict[str, Any]:
    labels = [label] if isinstance(label, str) else list(label)
    node: dict[str, Any] = {"labels": labels, "key": key, "props": props}
    if dense_vector is not None:
        node["dense_vector"] = list(dense_vector)
    return node


def make_edge(
    source: tuple[str, str],
    target: tuple[str, str],
    label: str,
    props: dict[str, Any] | None = None,
    *,
    valid_from: int | None = None,
    valid_to: int | None = None,
) -> dict[str, Any]:
    edge: dict[str, Any] = {
        "from": {"label": source[0], "key": source[1]},
        "to": {"label": target[0], "key": target[1]},
        "label": label,
        "props": props or {},
    }
    if valid_from is not None:
        edge["valid_from"] = valid_from
    if valid_to is not None:
        edge["valid_to"] = valid_to
    return edge


async def apply_batch(
    client: OwnerClient,
    prefix: str,
    *,
    nodes: list[dict],
    edges: list[dict],
    deletes: list[dict] | None = None,
) -> None:
    patch: dict[str, Any] = {"upsert_nodes": nodes, "upsert_edges": edges}
    if deletes:
        patch["delete_nodes"] = deletes
    result = await client.mutate(_mutation_id(prefix, patch), patch, kind="batch")
    if result.get("ok") is not True:
        raise OwnerGraphError(f"owner mutation failed: {result}")


async def read_nodes(
    client: OwnerClient,
    refs: list[tuple[str, str]],
    *,
    include_vectors: bool = False,
) -> dict[str, Any]:
    unique = list(dict.fromkeys(refs))
    if not unique:
        return {"values": {}, "ids": {}, "vectors": {}}
    return await client.read(
        [{"label": label, "key": key} for label, key in unique],
        include_vectors=include_vectors,
    )


def props_of(response: dict[str, Any], label: str, key: str) -> dict[str, Any] | None:
    return response.get("values", {}).get(f"{label}:{key}")


def id_of(response: dict[str, Any], label: str, key: str) -> int | None:
    return response.get("ids", {}).get(f"{label}:{key}")


def vector_of(response: dict[str, Any], label: str, key: str) -> list[float] | None:
    return response.get("vectors", {}).get(f"{label}:{key}")


async def neighbors_of(
    client: OwnerClient, node_id: int, label: str, *, limit: int = READ_LIMIT,
) -> list[dict[str, Any]]:
    """Bounded relation read that fails instead of silently truncating."""
    rows = await client.neighbors(node_id, labels=[label], limit=limit)
    if len(rows) >= limit:
        raise OwnerGraphError(f"owner relation {label} exceeds {limit} rows")
    return rows
