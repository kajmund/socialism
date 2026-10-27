"""In-memory mem0 vector store used to stage one extraction before Owner write."""

from __future__ import annotations

import math
import sys
import types
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from mem0.utils.factory import VectorStoreFactory
from mem0.vector_stores.base import VectorStoreBase
from mem0.vector_stores.configs import VectorStoreConfig

PROVIDER = "overgraph_staging"
CONFIG_CLASS = "StagingMem0Config"
_CURRENT: ContextVar[dict[str, dict[str, "StagedHit"]] | None] = ContextVar(
    "mem0_staging_root", default=None
)


@dataclass(frozen=True)
class StagedHit:
    id: str
    score: float | None
    payload: dict[str, Any]
    vector: tuple[float, ...]

    @property
    def memory(self) -> str:
        return str(self.payload.get("data") or "")


class StagingMem0Config:
    def __init__(
        self, collection_name: str = "expert_memories",
        embedding_model_dims: int = 1536, path: str | None = None,
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


def root() -> dict[str, dict[str, StagedHit]]:
    store = _CURRENT.get()
    if store is None:
        raise RuntimeError("mem0 staging store is not active")
    return store


def begin(seed: dict[str, dict[str, StagedHit]]) -> object:
    return _CURRENT.set(seed)


def end(token: object) -> None:
    _CURRENT.reset(token)  # type: ignore[arg-type]


class StagingVectorStore(VectorStoreBase):
    def __init__(
        self, collection_name: str = "expert_memories",
        embedding_model_dims: int = 1536, path: str | None = None,
        **_ignored: object,
    ) -> None:
        self.collection_name = collection_name
        self.embedding_model_dims = embedding_model_dims
        self.path = path

    @property
    def _collection(self) -> dict[str, StagedHit]:
        return root().setdefault(self.collection_name, {})

    def create_col(self, name=None, vector_size=None, distance=None) -> None:
        return None

    def insert(self, vectors, payloads=None, ids=None) -> None:
        payloads = payloads or [{}] * len(vectors)
        ids = ids or [str(index) for index in range(len(vectors))]
        for vector, payload, memory_id in zip(vectors, payloads, ids, strict=True):
            self._collection[str(memory_id)] = StagedHit(
                id=str(memory_id), score=None, payload=dict(payload or {}),
                vector=tuple(float(item) for item in vector),
            )

    def update(self, vector_id, vector=None, payload=None) -> None:
        existing = self._collection.get(str(vector_id))
        merged = dict(existing.payload if existing else {})
        if payload:
            merged.update(payload)
        self._collection[str(vector_id)] = StagedHit(
            id=str(vector_id), score=None, payload=merged,
            vector=tuple(float(item) for item in vector)
            if vector else (existing.vector if existing else ()),
        )

    def delete(self, vector_id) -> None:
        self._collection.pop(str(vector_id), None)

    def get(self, vector_id) -> StagedHit | None:
        return self._collection.get(str(vector_id))

    def _matches(self, hit: StagedHit, filters: dict[str, Any]) -> bool:
        return all(hit.payload.get(key) == value for key, value in filters.items())

    def search(self, query, vectors, top_k=5, filters=None) -> list[StagedHit]:
        filters = filters or {}
        query_vector = [float(item) for item in vectors]
        scored = []
        for hit in self._collection.values():
            if not self._matches(hit, filters) or not hit.vector:
                continue
            scored.append(StagedHit(
                id=hit.id, score=_cosine(query_vector, list(hit.vector)),
                payload=hit.payload, vector=hit.vector,
            ))
        scored.sort(key=lambda item: item.score or 0.0, reverse=True)
        return scored[:top_k]

    def list(self, filters=None, top_k=None) -> list[StagedHit]:
        filters = filters or {}
        hits = [hit for hit in self._collection.values() if self._matches(hit, filters)]
        return hits[:top_k] if top_k else hits

    def list_cols(self) -> list[str]:
        return list(root())

    def delete_col(self) -> None:
        root().pop(self.collection_name, None)

    def col_info(self) -> dict[str, Any]:
        return {"name": self.collection_name, "dimension": self.embedding_model_dims}

    def reset(self) -> None:
        self._collection.clear()


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return 0.0 if norm == 0 else dot / norm


_INSTALLED = False


def install_mem0_staging() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    providers = VectorStoreConfig.__private_attributes__["_provider_configs"].default
    providers[PROVIDER] = CONFIG_CLASS
    module_name = f"mem0.configs.vector_stores.{PROVIDER}"
    module = types.ModuleType(module_name)
    setattr(module, CONFIG_CLASS, StagingMem0Config)
    sys.modules[module_name] = module
    VectorStoreFactory.provider_to_class[PROVIDER] = (
        "app.services.expertgranskning.memory_staging.StagingVectorStore"
    )
    _INSTALLED = True
