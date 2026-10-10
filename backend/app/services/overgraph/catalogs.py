"""Process-owned OverGraph catalogs. One writer process; callers use the runtime."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, TypeVar

from overgraph import OverGraph

from app.services.overgraph.labels import (
    FACT,
    TEXT_UNIT,
    visible_scope_labels,
)
from app.services.overgraph.model import GraphRecord

T = TypeVar("T")

CatalogKind = Literal["knowledge", "memory"]


def _as_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    props = getattr(value, "props", None)
    if isinstance(props, dict):
        return dict(props)
    return {}


def _engine_id(value: object) -> int:
    if isinstance(value, int):
        return value
    for name in ("id", "node_id"):
        raw = getattr(value, name, None)
        if isinstance(raw, int):
            return raw
    raise TypeError(f"OverGraph id missing on {value!r}")


def _record(view: object) -> GraphRecord:
    labels = getattr(view, "labels", None) or ()
    if isinstance(labels, str):
        labels = (labels,)
    vector = getattr(view, "dense_vector", None) or getattr(view, "denseVector", None)
    return GraphRecord(
        key=str(getattr(view, "key", "")),
        labels=tuple(labels),
        props=_as_dict(view),
        engine_id=_engine_id(view),
        dense_vector=tuple(vector) if vector else None,
    )


class Catalog:
    """Thin locked wrapper around one OverGraph directory."""

    def __init__(self, db: Any, *, kind: CatalogKind, dimension: int, path: Path) -> None:
        self._db = db
        self.kind = kind
        self.dimension = dimension
        self.path = path
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            closer = getattr(self._db, "close", None)
            if closer is not None:
                closer()

    def read(self, fn: Callable[[Any], T]) -> T:
        """Run a read under the catalog lock so it cannot overlap a write."""
        with self._lock:
            return fn(self._db)

    def sync(self) -> None:
        with self._lock:
            self._db.sync()

    def ingest_mode(self) -> None:
        with self._lock:
            self._db.ingest_mode()

    def end_ingest(self) -> None:
        with self._lock:
            self._db.end_ingest()

    def upsert_node(
        self,
        labels: Sequence[str],
        key: str,
        *,
        props: dict[str, Any] | None = None,
        dense_vector: Sequence[float] | None = None,
        weight: float = 1.0,
    ) -> int:
        payload = dict(props or {})
        with self._lock:
            return _engine_id(self._db.upsert_node(
                list(labels), key, props=payload, dense_vector=dense_vector, weight=weight,
            ))

    def batch_upsert_nodes(self, nodes: Sequence[dict[str, Any]]) -> list[int]:
        with self._lock:
            result = self._db.batch_upsert_nodes(list(nodes))
        return [_engine_id(item) for item in result]

    def upsert_edge(
        self,
        source: int,
        target: int,
        label: str,
        *,
        props: dict[str, Any] | None = None,
        weight: float = 1.0,
        valid_from: int | None = None,
        valid_to: int | None = None,
    ) -> int:
        options: dict[str, Any] = {"props": dict(props or {}), "weight": weight}
        if valid_from is not None:
            options["valid_from"] = valid_from
        if valid_to is not None:
            options["valid_to"] = valid_to
        with self._lock:
            return _engine_id(self._db.upsert_edge(source, target, label, **options))

    def graph_patch(
        self,
        *,
        upsert_nodes: Sequence[dict[str, Any]] = (),
        upsert_edges: Sequence[dict[str, Any]] = (),
        invalidate_edges: Sequence[tuple[int, int]] = (),
        delete_node_ids: Sequence[int] = (),
        delete_edge_ids: Sequence[int] = (),
    ) -> None:
        with self._lock:
            self._db.graph_patch({
                "upsert_nodes": list(upsert_nodes),
                "upsert_edges": list(upsert_edges),
                "invalidate_edges": list(invalidate_edges),
                "delete_node_ids": list(delete_node_ids),
                "delete_edge_ids": list(delete_edge_ids),
            })

    def get_by_key(self, label: str, key: str) -> GraphRecord | None:
        with self._lock:
            view = self._db.get_node_by_key(label, key)
        if view is None:
            return None
        return _record(view)

    def get(self, engine_id: int) -> GraphRecord | None:
        with self._lock:
            view = self._db.get_node(engine_id)
        if view is None:
            return None
        return _record(view)

    def delete_node(self, engine_id: int) -> None:
        with self._lock:
            self._db.delete_node(engine_id)

    def vector_search(self, mode: str, request: dict[str, Any]) -> list[tuple[int, float]]:
        kwargs: dict[str, Any] = {"k": request["k"]}
        dense_query = request.get("dense_query")
        sparse_query = request.get("sparse_query")
        label_filter = request.get("label_filter")
        scope_start_node_id = request.get("scope_start_node_id")
        scope_max_depth = request.get("scope_max_depth")
        fusion_mode = request.get("fusion_mode")
        if dense_query is not None:
            kwargs["dense_query"] = list(dense_query)
        if sparse_query is not None:
            kwargs["sparse_query"] = list(sparse_query)
        if label_filter is not None:
            kwargs["label_filter"] = label_filter
        if scope_start_node_id is not None:
            kwargs["scope_start_node_id"] = scope_start_node_id
            kwargs["scope_max_depth"] = scope_max_depth or 2
        if fusion_mode is not None:
            kwargs["fusion_mode"] = fusion_mode
        with self._lock:
            hits = self._db.vector_search(mode, **kwargs)
        return [(_engine_id(hit), float(getattr(hit, "score", 0.0))) for hit in hits]

    def personalized_pagerank(
        self,
        seed_ids: Sequence[int],
        *,
        algorithm: str = "approx",
        max_results: int | None = 50,
        edge_label_filter: Sequence[str] | None = None,
    ) -> list[tuple[int, float]]:
        kwargs: dict[str, Any] = {"algorithm": algorithm, "max_results": max_results}
        if edge_label_filter is not None:
            kwargs["edge_label_filter"] = list(edge_label_filter)
        with self._lock:
            result = self._db.personalized_pagerank(list(seed_ids), **kwargs)
        ids = list(getattr(result, "node_ids", ()))
        scores = list(getattr(result, "scores", ()))
        return [(int(node_id), float(score)) for node_id, score in zip(ids, scores, strict=True)]

    def top_k_neighbors(
        self, engine_id: int, k: int, *, direction: str = "outgoing",
    ) -> list[tuple[int, float]]:
        with self._lock:
            hits = self._db.top_k_neighbors(engine_id, k, direction=direction)
        return [(_engine_id(hit), float(getattr(hit, "weight", getattr(hit, "score", 0.0))))
                for hit in hits]

    def neighbors(
        self, engine_id: int, *, direction: str = "outgoing",
        edge_label_filter: Sequence[str] | None = None, limit: int | None = None,
    ) -> list[int]:
        kwargs: dict[str, Any] = {"direction": direction}
        if edge_label_filter is not None:
            kwargs["edge_label_filter"] = list(edge_label_filter)
        if limit is not None:
            kwargs["limit"] = limit
        with self._lock:
            entries = self._db.neighbors(engine_id, **kwargs)
        return [_engine_id(getattr(entry, "node_id", entry)) for entry in entries]

    def traverse(
        self, engine_id: int, max_depth: int, *, direction: str = "outgoing",
    ) -> list[tuple[int, int]]:
        with self._lock:
            result = self._db.traverse(engine_id, max_depth, direction=direction)
        items = getattr(result, "items", result)
        if isinstance(items, dict):
            items = items.values()
        out: list[tuple[int, int]] = []
        for item in items:
            node_id = getattr(item, "node_id", None)
            depth = getattr(item, "depth", 1)
            if node_id is None and isinstance(item, (list, tuple)):
                node_id, depth = item[0], item[1]
            if node_id is not None:
                out.append((_engine_id(node_id), int(depth)))
        return out

    def scoped_type_search(
        self, *, kind: str, customer_id: int | None, k: int,
        dense_query: Sequence[float], mode: str = "dense",
        sparse_query: Sequence[tuple[int, float]] | None = None,
    ) -> list[tuple[int, float]]:
        """Search each visible scope label before top-k, then merge."""
        merged: dict[int, float] = {}
        for scope in visible_scope_labels(customer_id):
            hits = self.vector_search(mode, {
                "k": k,
                "dense_query": dense_query,
                "sparse_query": sparse_query,
                "label_filter": {"labels": [kind, scope], "mode": "all"},
            })
            for engine_id, score in hits:
                merged[engine_id] = max(score, merged.get(engine_id, score))
        return sorted(merged.items(), key=lambda item: item[1], reverse=True)[:k]

    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        return await asyncio.to_thread(fn, *args)


class OverGraphRuntime:
    def __init__(self, knowledge: Catalog, memory: Catalog) -> None:
        self.knowledge = knowledge
        self.memory = memory

    def close(self) -> None:
        self.knowledge.close()
        self.memory.close()


_runtime: OverGraphRuntime | None = None


def open_catalog(path: Path, *, kind: CatalogKind, dimension: int) -> Catalog:
    path.mkdir(parents=True, exist_ok=True)
    db = OverGraph.open(
        str(path),
        create_if_missing=True,
        dense_vector_dimension=dimension,
        dense_vector_metric="cosine",
        wal_sync_mode="group_commit",
        edge_uniqueness=True,
    )
    return Catalog(db, kind=kind, dimension=dimension, path=path)


def catalog_root(directory: str) -> Path:
    root = Path(directory)
    return root if root.is_absolute() else Path.cwd() / root


def open_runtime(
    root: Path, *, knowledge_dimension: int, memory_dimension: int,
) -> OverGraphRuntime:
    return OverGraphRuntime(
        open_catalog(root / "knowledge", kind="knowledge", dimension=knowledge_dimension),
        open_catalog(root / "memory", kind="memory", dimension=memory_dimension),
    )


def set_runtime(runtime: OverGraphRuntime | None) -> None:
    global _runtime
    if _runtime is not None and runtime is not _runtime:
        _runtime.close()
    _runtime = runtime


def get_runtime() -> OverGraphRuntime | None:
    return _runtime


def require_knowledge() -> Catalog:
    if _runtime is None:
        raise RuntimeError("OverGraph knowledge catalog is not open")
    return _runtime.knowledge


def require_memory() -> Catalog:
    if _runtime is None:
        raise RuntimeError("OverGraph memory catalog is not open")
    return _runtime.memory


def knowledge_type_for(kind: str) -> str:
    if kind == "fact":
        return FACT
    if kind == "text_unit":
        return TEXT_UNIT
    raise ValueError(f"unsupported knowledge search kind: {kind}")
