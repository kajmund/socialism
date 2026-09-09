"""KnowledgeVectorStore boundary. Vector Bucket SDK shape stays in this module.

Analytics Buckets are a later warehouse concern and are not on this path.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    EmbeddedKnowledgeQuery,
    KnowledgeChunk,
    KnowledgeHit,
    KnowledgeScope,
    require_scope,
    scope_allows,
    scope_of,
)
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID, KnowledgeVectorStoreError


class KnowledgeVectorStore(Protocol):
    async def upsert_chunks(self, chunks: Sequence[EmbeddedKnowledgeChunk]) -> None: ...

    async def replace_document_chunks(
        self,
        document_id: str,
        chunks: Sequence[EmbeddedKnowledgeChunk],
    ) -> None: ...

    async def search(self, query: EmbeddedKnowledgeQuery) -> list[KnowledgeHit]: ...

    async def delete_document(self, document_id: str) -> None: ...


@dataclass(frozen=True)
class VectorBucketRecord:
    """Adapter DTO for the alpha Vector Bucket transport. Not a public API type."""

    document_id: str
    chunk_id: str
    text: str
    title: str
    score: float | None = None
    locator: str | None = None
    provider: str | None = None
    version: str | None = None
    external_id: str | None = None
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorBucketClient(Protocol):
    """Replaceable transport. Live Supabase Vector Bucket SDK belongs here later."""

    async def upsert(self, records: Sequence[VectorBucketRecord]) -> None: ...

    async def replace(
        self,
        document_id: str,
        records: Sequence[VectorBucketRecord],
    ) -> None: ...

    async def query(
        self,
        *,
        vector: Sequence[float],
        filters: Mapping[str, Any],
        limit: int,
    ) -> Sequence[VectorBucketRecord]: ...

    async def delete(self, document_id: str) -> None: ...


def scope_filters(scope: KnowledgeScope) -> dict[str, Any]:
    require_scope(scope)
    filters: dict[str, Any] = {"customer_id": scope.customer_id}
    if scope.case_id is not None:
        filters["case_id"] = scope.case_id
    if scope.module is not None:
        filters["module"] = scope.module
    return filters


def record_in_scope(record: VectorBucketRecord, scope: KnowledgeScope) -> bool:
    meta = record.metadata
    customer_id = _optional_int(meta.get("customer_id"))
    if customer_id is None:
        return False
    owned = scope_of(
        customer_id=customer_id,
        case_id=_optional_str(meta.get("case_id")),
        module=_optional_str(meta.get("module")),
    )
    return scope_allows(owned=owned, requested=scope)


def chunk_in_scope(chunk: KnowledgeChunk, scope: KnowledgeScope) -> bool:
    owned = scope_of(
        customer_id=chunk.customer_id,
        case_id=chunk.case_id,
        module=chunk.module,
    )
    return scope_allows(owned=owned, requested=scope)


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def cosine_score(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise KnowledgeVectorStoreError(
            f"Query embedding dimension {len(left)} does not match stored dimension {len(right)}"
        )
    if not left:
        raise KnowledgeVectorStoreError("Embedding must not be empty")
    dot = math.fsum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def hit_from_chunk(chunk: KnowledgeChunk, *, score: float | None) -> KnowledgeHit:
    return KnowledgeHit(
        document_id=chunk.document_id,
        provider=chunk.provider or SUPABASE_PROVIDER_ID,
        title=chunk.title,
        excerpt=chunk.text,
        score=score,
        locator=chunk.locator,
        metadata=dict(chunk.metadata),
    )


def hit_from_record(record: VectorBucketRecord) -> KnowledgeHit:
    return KnowledgeHit(
        document_id=record.document_id,
        provider=record.provider or SUPABASE_PROVIDER_ID,
        title=record.title,
        excerpt=record.text,
        score=record.score,
        locator=record.locator,
        external_id=record.external_id,
        metadata=dict(record.metadata),
    )


def chunk_to_record(
    chunk: KnowledgeChunk,
    *,
    embedding: Sequence[float] | None = None,
) -> VectorBucketRecord:
    metadata = {
        **chunk.metadata,
        "document_id": chunk.document_id,
        "chunk_id": chunk.chunk_id,
        "customer_id": chunk.customer_id,
        "case_id": chunk.case_id,
        "module": chunk.module,
        "title": chunk.title,
        "locator": chunk.locator,
        "provider": chunk.provider,
        "version": chunk.version,
        "content_hash": chunk.content_hash,
    }
    return VectorBucketRecord(
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        text=chunk.text,
        title=chunk.title,
        locator=chunk.locator,
        provider=chunk.provider,
        version=chunk.version,
        embedding=list(embedding or ()),
        metadata=metadata,
    )


def embedded_chunk_to_record(item: EmbeddedKnowledgeChunk) -> VectorBucketRecord:
    return chunk_to_record(item.chunk, embedding=item.embedding)


class MemoryKnowledgeVectorStore:
    """In-process store for tests. Same contract as the Vector Bucket adapter."""

    def __init__(self) -> None:
        self._chunks: list[EmbeddedKnowledgeChunk] = []

    @property
    def chunks(self) -> list[EmbeddedKnowledgeChunk]:
        return list(self._chunks)

    async def upsert_chunks(self, chunks: Sequence[EmbeddedKnowledgeChunk]) -> None:
        ids = {(item.chunk.document_id, item.chunk.chunk_id) for item in chunks}
        self._chunks = [
            existing
            for existing in self._chunks
            if (existing.chunk.document_id, existing.chunk.chunk_id) not in ids
        ]
        self._chunks.extend(chunks)

    async def replace_document_chunks(
        self,
        document_id: str,
        chunks: Sequence[EmbeddedKnowledgeChunk],
    ) -> None:
        kept = [item for item in self._chunks if item.chunk.document_id != document_id]
        self._chunks = kept + list(chunks)

    async def search(self, query: EmbeddedKnowledgeQuery) -> list[KnowledgeHit]:
        require_scope(query.query.scope)
        scored: list[tuple[float, KnowledgeChunk]] = []
        for item in self._chunks:
            chunk = item.chunk
            if not chunk_in_scope(chunk, query.query.scope):
                continue
            score = cosine_score(query.embedding, item.embedding)
            if score <= 0:
                continue
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit_from_chunk(chunk, score=score) for score, chunk in scored[: query.query.limit]]

    async def delete_document(self, document_id: str) -> None:
        self._chunks = [item for item in self._chunks if item.chunk.document_id != document_id]


class SupabaseVectorBucketStore:
    """First Vector Bucket adapter. Client is injected so the alpha SDK can change."""

    def __init__(self, client: VectorBucketClient) -> None:
        self._client = client

    async def upsert_chunks(self, chunks: Sequence[EmbeddedKnowledgeChunk]) -> None:
        await self._client.upsert([embedded_chunk_to_record(item) for item in chunks])

    async def replace_document_chunks(
        self,
        document_id: str,
        chunks: Sequence[EmbeddedKnowledgeChunk],
    ) -> None:
        await self._client.replace(
            document_id,
            [embedded_chunk_to_record(item) for item in chunks],
        )

    async def search(self, query: EmbeddedKnowledgeQuery) -> list[KnowledgeHit]:
        filters = scope_filters(query.query.scope)
        try:
            records = await self._client.query(
                vector=query.embedding,
                filters=filters,
                limit=query.query.limit,
            )
        except KnowledgeVectorStoreError:
            raise
        except Exception as exc:
            raise KnowledgeVectorStoreError(f"Vector Bucket query failed: {exc}") from exc
        hits: list[KnowledgeHit] = []
        for record in records:
            if not record_in_scope(record, query.query.scope):
                continue
            hits.append(hit_from_record(record))
            if len(hits) >= query.query.limit:
                break
        return hits

    async def delete_document(self, document_id: str) -> None:
        await self._client.delete(document_id)
