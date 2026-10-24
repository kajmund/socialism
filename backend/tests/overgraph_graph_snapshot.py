"""Semantic Overgraph snapshot shared by direct-vs-owner differential tests.

Owner receipts and wall-clock stamps carry no fact semantics, so they are the
only things normalized. Fact-Fact ``CONTRADICTS`` is undirected but both writers
use one canonical key-sorted orientation, so the snapshot compares it directed.
"""

from __future__ import annotations

import time
from typing import Any

from app.services.overgraph.catalogs import Catalog

NODE_LABELS = ("Fact", "Entity", "TextUnit", "DocumentVersion", "Identifier")
EDGE_LABELS = (
    "SUBJECT", "OBJECT", "CONTEXT", "SUPPORTS", "CONTRADICTS", "DEPENDS_ON",
    "CONTAINS", "NEXT",
)
VOLATILE_NODE_PROPS = {"created_at_ms", "ingested_at"}
VOLATILE_EDGE_PROPS = {"recorded_at"}
# OverGraph stamps omitted valid_from/valid_to with the creation instant. That
# default has no fact semantics; a deliberate temporal window is far from now.
CREATED_TIMESTAMP_WINDOW_MS = 10 * 60 * 1000


def _edge_time(value: int | None, now_ms: int) -> object:
    if value is None:
        return None
    return "<created>" if abs(value - now_ms) < CREATED_TIMESTAMP_WINDOW_MS else value


def _props(props: dict[str, Any], volatile: set[str]) -> tuple[tuple[str, Any], ...]:
    return tuple(
        (name, "<timestamp>" if name in volatile else value)
        for name, value in sorted(props.items())
    )


def graph_snapshot(catalog: Catalog) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    engine_ids: dict[str, int] = {}
    for label in NODE_LABELS:
        rows, _ = catalog.query_nodes(
            label_filter={"labels": [label], "mode": "all"}, limit=10_000,
        )
        for row in rows:
            if row.engine_id is None:
                continue
            engine_ids[row.key] = row.engine_id
            nodes[row.key] = {
                "labels": tuple(sorted(row.labels)),
                "props": _props(row.props, VOLATILE_NODE_PROPS),
                "dense_vector": tuple(row.dense_vector) if row.dense_vector else None,
            }
    key_by_engine = {engine_id: key for key, engine_id in engine_ids.items()}
    now_ms = int(time.time() * 1000)
    edges: set[tuple[Any, ...]] = set()
    for source_key, engine_id in engine_ids.items():
        for label in EDGE_LABELS:
            for neighbor in catalog.neighbors(
                engine_id, direction="outgoing", edge_label_filter=[label],
            ):
                target_key = key_by_engine.get(neighbor)
                if target_key is None:
                    continue
                edge = catalog.get_edge_by_triple(engine_id, neighbor, label)
                if edge is None:
                    continue
                edges.add((
                    (source_key, target_key),
                    label,
                    _props(edge.props, VOLATILE_EDGE_PROPS),
                    _edge_time(edge.valid_from, now_ms),
                    _edge_time(edge.valid_to, now_ms),
                ))
    return {"nodes": nodes, "edges": frozenset(edges)}
