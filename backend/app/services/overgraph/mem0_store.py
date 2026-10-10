"""Mem0 VectorStoreBase adapter. Expert chat never calls this store directly."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mem0.vector_stores.base import VectorStoreBase

from app.services.overgraph.catalogs import Catalog, require_memory
from app.services.overgraph.labels import LINKED, MEMORY, MEMORY_ENTITY, agent_label, user_label


@dataclass
class MemoryHit:
    id: str | None
    score: float | None
    payload: dict[str, Any] | None


def _kind(collection_name: str) -> str:
    return MEMORY_ENTITY if collection_name.endswith("_entities") else MEMORY


def _payload(raw: dict[str, Any] | None) -> dict[str, Any]:
    return dict(raw or {})


class OverGraphMem0Config:
    """Shape mem0 expects after VectorStoreConfig validation."""

    def __init__(
        self,
        collection_name: str = "expert_memories",
        embedding_model_dims: int = 1536,
        path: str | None = None,
        **_ignored: object,
    ) -> None:
        self.collection_name = collection_name
        self.embedding_model_dims = embedding_model_dims
        self.path = path

    def model_dump(self) -> dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "embedding_model_dims": self.embedding_model_dims,
            "path": self.path,
        }


class OverGraphVectorStore(VectorStoreBase):
    def __init__(
        self,
        collection_name: str = "expert_memories",
        embedding_model_dims: int = 1536,
        path: str | None = None,
        catalog: Catalog | None = None,
        **_ignored: object,
    ) -> None:
        self.collection_name = collection_name
        self.embedding_model_dims = embedding_model_dims
        self.path = path
        self._catalog = catalog
        self._kind = _kind(collection_name)

    @property
    def catalog(self) -> Catalog:
        return self._catalog if self._catalog is not None else require_memory()

    def create_col(self, name=None, vector_size=None, distance=None) -> None:
        return None

    def insert(self, vectors, payloads=None, ids=None) -> None:
        payloads = payloads or [{}] * len(vectors)
        ids = ids or [str(index) for index in range(len(vectors))]
        for vector, payload, memory_id in zip(vectors, payloads, ids, strict=True):
            self._upsert(str(memory_id), list(vector), _payload(payload))

    def update(self, vector_id, vector=None, payload=None) -> None:
        existing = self.get(vector_id)
        merged = _payload(existing.payload if existing else None)
        if payload:
            merged.update(payload)
        dense = vector
        if dense is None and existing is not None:
            row = self.catalog.get_by_key(self._kind, str(vector_id))
            dense = list(row.dense_vector) if row and row.dense_vector else []
        self._upsert(str(vector_id), list(dense or []), merged)

    def _upsert(self, memory_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        user_id = str(payload.get("user_id") or "")
        agent_id = str(payload.get("agent_id") or "")
        labels = [self._kind]
        if user_id:
            labels.append(user_label(user_id))
        if agent_id:
            labels.append(agent_label(agent_id))
        engine_id = self.catalog.upsert_node(
            labels,
            memory_id,
            props={
                "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "user_id": user_id,
                "agent_id": agent_id,
                "collection": self.collection_name,
            },
            dense_vector=vector or None,
        )
        for linked in payload.get("linked_memory_ids") or ():
            other = self.catalog.get_by_key(MEMORY, str(linked))
            if other is not None and other.engine_id is not None:
                self.catalog.upsert_edge(engine_id, other.engine_id, LINKED)

    def search(self, query, vectors, top_k=5, filters=None) -> list[MemoryHit]:
        labels = [self._kind]
        filters = filters or {}
        if filters.get("user_id"):
            labels.append(user_label(str(filters["user_id"])))
        if filters.get("agent_id"):
            labels.append(agent_label(str(filters["agent_id"])))
        hits = self.catalog.vector_search("dense", {
            "k": top_k,
            "dense_query": list(vectors),
            "label_filter": {"labels": labels, "mode": "all"},
        })
        out: list[MemoryHit] = []
        for engine_id, score in hits:
            row = self.catalog.get(engine_id)
            if row is None:
                continue
            payload = json.loads(str(row.props.get("payload_json") or "{}"))
            if filters.get("user_id") and payload.get("user_id") != filters["user_id"]:
                continue
            if filters.get("agent_id") and payload.get("agent_id") != filters["agent_id"]:
                continue
            neighbors = []
            if row.engine_id is not None:
                neighbors = self.catalog.neighbors(row.engine_id, edge_label_filter=[LINKED])
            if neighbors:
                payload = {**payload, "linked_count": len(neighbors)}
            out.append(MemoryHit(id=row.key, score=score, payload=payload))
        return out

    def delete(self, vector_id) -> None:
        row = self.catalog.get_by_key(self._kind, str(vector_id))
        if row is not None and row.engine_id is not None:
            self.catalog.delete_node(row.engine_id)

    def get(self, vector_id) -> MemoryHit | None:
        row = self.catalog.get_by_key(self._kind, str(vector_id))
        if row is None:
            return None
        payload = json.loads(str(row.props.get("payload_json") or "{}"))
        return MemoryHit(id=row.key, score=None, payload=payload)

    def list(self, filters=None, top_k=None) -> list[MemoryHit]:
        filters = filters or {}
        labels = [self._kind]
        if filters.get("user_id"):
            labels.append(user_label(str(filters["user_id"])))
        if filters.get("agent_id"):
            labels.append(agent_label(str(filters["agent_id"])))
        dummy = [0.0] * self.embedding_model_dims
        hits = self.catalog.vector_search("dense", {
            "k": top_k or 10_000,
            "dense_query": dummy,
            "label_filter": {"labels": labels, "mode": "all"},
        })
        out: list[MemoryHit] = []
        for engine_id, score in hits:
            row = self.catalog.get(engine_id)
            if row is None:
                continue
            payload = json.loads(str(row.props.get("payload_json") or "{}"))
            out.append(MemoryHit(id=row.key, score=score, payload=payload))
        return out

    def list_cols(self) -> list[str]:
        return [self.collection_name]

    def delete_col(self) -> None:
        return None

    def col_info(self) -> dict[str, Any]:
        return {
            "name": self.collection_name,
            "dimension": self.embedding_model_dims,
        }

    def reset(self) -> None:
        return None
