"""Supabase knowledge provider: Files bucket originals + vector-store search."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeDocumentRecord
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.models import (
    EmbeddedKnowledgeQuery,
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    require_scope,
    scope_allows,
    scope_of,
)
from app.services.knowledge.provider import (
    SUPABASE_PROVIDER_ID,
    KnowledgeNotFoundError,
)
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.object_storage import get_object

ObjectFetcher = Callable[[str, str], Awaitable[tuple[bytes, str]]]
_SEARCH_OVERFETCH_FACTOR = 8


def supabase_external_id(bucket: str, key: str) -> str:
    return f"{bucket}/{key}"


class SupabaseKnowledgeProvider:
    provider_id = SUPABASE_PROVIDER_ID

    def __init__(
        self,
        session: AsyncSession,
        vector_store: KnowledgeVectorStore,
        embeddings: EmbeddingProvider,
        *,
        fetch_object: ObjectFetcher | None = None,
    ) -> None:
        self._session = session
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._fetch_object = fetch_object or get_object

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        require_scope(query.scope)
        vectors = await self._embeddings.embed([query.query])
        if len(vectors) != 1:
            raise RuntimeError(f"EmbeddingProvider returned {len(vectors)} vectors for 1 query")
        embedding = vectors[0]
        allowed: list[KnowledgeHit] = []
        seen: set[tuple[str, str | None]] = set()
        fetch_limit = query.limit
        max_fetch = query.limit * _SEARCH_OVERFETCH_FACTOR
        while len(allowed) < query.limit:
            raw_hits = await self._vector_store.search(
                EmbeddedKnowledgeQuery(
                    query=KnowledgeQuery(query=query.query, scope=query.scope, limit=fetch_limit),
                    embedding=embedding,
                )
            )
            for hit in raw_hits:
                key = (hit.document_id, hit.locator)
                if key in seen:
                    continue
                seen.add(key)
                visible = await self._accepted_hit(hit, query.scope)
                if visible is None:
                    continue
                allowed.append(visible)
                if len(allowed) >= query.limit:
                    return allowed
            if len(raw_hits) < fetch_limit or fetch_limit >= max_fetch:
                break
            fetch_limit = min(fetch_limit * 2, max_fetch)
        return allowed

    async def get_document(
        self,
        document_id: str,
        scope: KnowledgeScope,
    ) -> KnowledgeDocument | None:
        require_scope(scope)
        row = await self._row(document_id)
        if row is None or not self._visible(row, scope):
            return None
        return self._to_document(row)

    async def fetch_content(self, document_id: str, scope: KnowledgeScope) -> bytes:
        require_scope(scope)
        row = await self._row(document_id)
        if row is None or not self._visible(row, scope):
            raise KnowledgeNotFoundError(document_id)
        if not row.storage_bucket or not row.storage_key:
            raise KnowledgeNotFoundError(document_id)
        data, _content_type = await self._fetch_object(row.storage_bucket, row.storage_key)
        return data

    async def _accepted_hit(
        self,
        hit: KnowledgeHit,
        scope: KnowledgeScope,
    ) -> KnowledgeHit | None:
        if hit.provider != self.provider_id:
            return None
        row = await self._row(hit.document_id)
        if row is None or not self._visible(row, scope):
            return None
        return KnowledgeHit(
            document_id=row.document_id,
            provider=row.provider,
            title=hit.title or row.title,
            excerpt=hit.excerpt,
            score=hit.score,
            locator=hit.locator,
            external_id=row.external_id,
            metadata={**dict(row.extra or {}), **hit.metadata},
        )

    async def _row(self, document_id: str) -> KnowledgeDocumentRecord | None:
        result = await self._session.execute(
            select(KnowledgeDocumentRecord).where(
                KnowledgeDocumentRecord.document_id == document_id,
                KnowledgeDocumentRecord.provider == self.provider_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _visible(row: KnowledgeDocumentRecord, scope: KnowledgeScope) -> bool:
        owned = scope_of(
            customer_id=row.customer_id,
            case_id=row.case_id,
            module=row.module,
        )
        return scope_allows(owned=owned, requested=scope)

    @staticmethod
    def _to_document(row: KnowledgeDocumentRecord) -> KnowledgeDocument:
        return KnowledgeDocument(
            document_id=row.document_id,
            provider=row.provider,
            external_id=row.external_id,
            title=row.title,
            mime_type=row.mime_type,
            scope=scope_of(
                customer_id=row.customer_id,
                case_id=row.case_id,
                module=row.module,
            ),
            version=row.version,
            metadata=dict(row.extra or {}),
        )
