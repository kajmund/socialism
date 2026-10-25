"""Shared Owner protocol helpers for tenant Q&A modules."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.services.overgraph.owner import OwnerClient

READ_LIMIT = 200


class OwnerQaError(RuntimeError):
    """Owner rejected or lost a tenant Q&A write."""


@dataclass
class _Batch:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


def _mutation_id(prefix: str, patch: dict[str, Any]) -> str:
    canonical = json.dumps(patch, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"


def _node(
    label: str,
    key: str,
    props: dict[str, Any],
    *,
    dense_vector: list[float] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"labels": [label], "key": key, "props": props}
    if dense_vector is not None:
        node["dense_vector"] = list(dense_vector)
    return node


def _edge(
    source: tuple[str, str],
    target: tuple[str, str],
    label: str,
    props: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "from": {"label": source[0], "key": source[1]},
        "to": {"label": target[0], "key": target[1]},
        "label": label,
        "props": props or {},
    }


async def _apply(
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
        raise OwnerQaError(f"owner qa mutation failed: {result}")


async def _read(
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


def _props(response: dict[str, Any], label: str, key: str) -> dict[str, Any] | None:
    return response.get("values", {}).get(f"{label}:{key}")


def _node_id(response: dict[str, Any], label: str, key: str) -> int | None:
    return response.get("ids", {}).get(f"{label}:{key}")


def _vector(response: dict[str, Any], label: str, key: str) -> list[float] | None:
    return response.get("vectors", {}).get(f"{label}:{key}")


async def _neighbors(
    client: OwnerClient, node_id: int, label: str, *, limit: int = READ_LIMIT,
) -> list[dict[str, Any]]:
    """Bounded relation read that fails instead of silently truncating."""
    rows = await client.neighbors(node_id, labels=[label], limit=limit)
    if len(rows) >= limit:
        raise OwnerQaError(f"owner relation {label} exceeds {limit} rows")
    return rows
