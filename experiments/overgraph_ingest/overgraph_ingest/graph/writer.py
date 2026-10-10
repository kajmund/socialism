"""Single-handle OverGraph writer: batch upserts, then a small publish txn."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from overgraph import OverGraph

from overgraph_ingest.graph.builder import EdgeDraft, GraphDraft, NodeDraft
from overgraph_ingest.graph.stats import BatchWrite, WriteStats


class GraphWriter:
    def __init__(self, db: OverGraph, *, batch_size: int) -> None:
        self.db = db
        self.batch_size = batch_size
        self.key_to_id: dict[tuple[str, str], int] = {}

    def write_draft(self, draft: GraphDraft) -> WriteStats:
        stats = WriteStats()
        self._upsert_nodes(draft.nodes, stats)
        self._upsert_edges(draft.edges, stats)
        return stats

    def publish_document(self, key: str, props: dict[str, object]) -> None:
        txn = self.db.begin_write_txn()
        try:
            txn.upsert_node(["Document"], key, props=props)
            txn.commit()
        except Exception:
            txn.rollback()
            raise

    def get_document(self, key: str) -> Any | None:
        return self.db.get_node_by_key("Document", key)

    def get_node(self, label: str, key: str) -> Any | None:
        return self.db.get_node_by_key(label, key)

    def iter_nodes(self, label: str):
        after = None
        while True:
            page = self.db.get_nodes_by_labels_paged([label], limit=256, after=after)
            items = list(page.items)
            if not items:
                return
            yield from items
            if page.next_cursor is None:
                return
            after = page.next_cursor

    def write_vectors(self, nodes: list[dict[str, object]]) -> None:
        for start in range(0, len(nodes), self.batch_size):
            self.db.batch_upsert_nodes(nodes[start : start + self.batch_size])

    def _upsert_nodes(self, nodes: list[NodeDraft], stats: WriteStats) -> None:
        for start in range(0, len(nodes), self.batch_size):
            batch = nodes[start : start + self.batch_size]
            payload = [
                {"labels": list(node.labels), "key": node.key, "props": dict(node.props)}
                for node in batch
            ]
            started = time.perf_counter()
            ids = self.db.batch_upsert_nodes(payload)
            seconds = time.perf_counter() - started
            stats.node_seconds += seconds
            stats.nodes += len(payload)
            stats.batches.append(BatchWrite("nodes", len(payload), seconds))
            for node, node_id in zip(batch, ids, strict=True):
                self.key_to_id[(node.labels[0], node.key)] = node_id

    def _upsert_edges(self, edges: list[EdgeDraft], stats: WriteStats) -> None:
        payload: list[dict[str, object]] = []
        for edge in edges:
            from_id = self._require_id(edge.from_label, edge.from_key)
            to_id = self._require_id(edge.to_label, edge.to_key)
            payload.append(
                {
                    "from_id": from_id,
                    "to_id": to_id,
                    "label": edge.label,
                }
            )
        for start in range(0, len(payload), self.batch_size):
            chunk = payload[start : start + self.batch_size]
            started = time.perf_counter()
            self.db.batch_upsert_edges(chunk)
            seconds = time.perf_counter() - started
            stats.edge_seconds += seconds
            stats.edges += len(chunk)
            stats.batches.append(BatchWrite("edges", len(chunk), seconds))

    def _require_id(self, label: str, key: str) -> int:
        cached = self.key_to_id.get((label, key))
        if cached is not None:
            return cached
        view = self.db.get_node_by_key(label, key)
        if view is None:
            raise KeyError(f"missing node {label}:{key}")
        self.key_to_id[(label, key)] = view.id
        return view.id


def open_database(path: Path, dimension: int) -> OverGraph:
    path.mkdir(parents=True, exist_ok=True)
    return OverGraph.open(
        str(path),
        create_if_missing=True,
        dense_vector_dimension=dimension,
        dense_vector_metric="cosine",
        wal_sync_mode="group_commit",
        edge_uniqueness=True,
    )


def read_manifest_dimension(path: Path) -> int | None:
    manifest = path / "manifest.current"
    if not manifest.is_file():
        return None
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    dense = payload.get("dense_vector") or {}
    dimension = dense.get("dimension")
    if dimension is None:
        return None
    return int(dimension)


def resolve_dimension(path: Path, requested: int | None) -> int:
    existing = read_manifest_dimension(path)
    if existing is not None:
        if requested is not None and requested != existing:
            raise ValueError(
                f"database {path} is locked to dense dimension {existing}, "
                f"got --dense-dimension {requested}"
            )
        return existing
    if requested is None:
        raise ValueError("--dense-dimension is required when creating a new database")
    return requested
