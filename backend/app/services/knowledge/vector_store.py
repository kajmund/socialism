"""KnowledgeVectorStore boundary. Vector Bucket SDK shape stays in this module.

Analytics Buckets are a later warehouse concern and are not on this path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.knowledge.models import (
    KnowledgeChunk,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    require_scope,
    scope_allows,
    scope_of,
)
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID, KnowledgeVectorStoreError


class KnowledgeVectorStore(Protocol):
    async def upsert_chunks(self, chunks: Sequence[KnowledgeChunk]) -> None: ...

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]: ...

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
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorBucketClient(Protocol):
    """Replaceable transport. Live Supabase Vector Bucket SDK belongs here later."""

    async def upsert(self, records: Sequence[VectorBucketRecord]) -> None: ...

    async def query(
        self,
        *,
        query: str,
        filters: Mapping[str, Any],
        limit: int,
    ) -> Sequence[VectorBucketRecord]: ...

    async def delete(self, document_id: str) -> None: ...


def scope_filters(scope: KnowledgeScope) -> dict[str, Any]:
    require_scope(scope)
    filters: dict[str, Any] = {}
    if scope.customer_id is not None:
        filters["customer_id"] = scope.customer_id
    if scope.case_id is not None:
        filters["case_id"] = scope.case_id
    if scope.module is not None:
        filters["module"] = scope.module
    return filters


def record_in_scope(record: VectorBucketRecord, scope: KnowledgeScope) -> bool:
    meta = record.metadata
    owned = scope_of(
        customer_id=_optional_int(meta.get("customer_id")),
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


def _lexical_score(query: str, text: str) -> float:
    words = [part for part in query.lower().split() if part]
    if not words:
        return 0.0
    haystack = text.lower()
    if query.strip().lower() in haystack:
        return 1.0
    hits = sum(1 for word in words if word in haystack)
    return hits / len(words)


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


def chunk_to_record(chunk: KnowledgeChunk) -> VectorBucketRecord:
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
    }
    return VectorBucketRecord(
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        text=chunk.text,
        title=chunk.title,
        locator=chunk.locator,
        provider=chunk.provider,
        version=chunk.version,
        metadata=metadata,
    )


class MemoryKnowledgeVectorStore:
    """In-process store for tests. Same contract as the Vector Bucket adapter."""

    def __init__(self) -> None:
        self._chunks: list[KnowledgeChunk] = []

    async def upsert_chunks(self, chunks: Sequence[KnowledgeChunk]) -> None:
        ids = {(chunk.document_id, chunk.chunk_id) for chunk in chunks}
        self._chunks = [
            existing
            for existing in self._chunks
            if (existing.document_id, existing.chunk_id) not in ids
        ]
        self._chunks.extend(chunks)

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        require_scope(query.scope)
        scored: list[tuple[float, KnowledgeChunk]] = []
        for chunk in self._chunks:
            if not chunk_in_scope(chunk, query.scope):
                continue
            score = _lexical_score(query.query, chunk.text)
            if score <= 0:
                continue
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit_from_chunk(chunk, score=score) for score, chunk in scored[: query.limit]]

    async def delete_document(self, document_id: str) -> None:
        self._chunks = [chunk for chunk in self._chunks if chunk.document_id != document_id]


class SupabaseVectorBucketStore:
    """First Vector Bucket adapter. Client is injected so the alpha SDK can change."""

    def __init__(self, client: VectorBucketClient) -> None:
        self._client = client

    async def upsert_chunks(self, chunks: Sequence[KnowledgeChunk]) -> None:
        await self._client.upsert([chunk_to_record(chunk) for chunk in chunks])

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        filters = scope_filters(query.scope)
        try:
            records = await self._client.query(
                query=query.query,
                filters=filters,
                limit=query.limit,
            )
        except KnowledgeVectorStoreError:
            raise
        except Exception as exc:
            raise KnowledgeVectorStoreError(f"Vector Bucket query failed: {exc}") from exc
        hits: list[KnowledgeHit] = []
        for record in records:
            if not record_in_scope(record, query.scope):
                continue
            hits.append(hit_from_record(record))
            if len(hits) >= query.limit:
                break
        return hits

    async def delete_document(self, document_id: str) -> None:
        await self._client.delete(document_id)
