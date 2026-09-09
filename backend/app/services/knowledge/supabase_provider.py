"""Supabase knowledge provider: Files bucket originals + vector-store search."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeDocumentRecord
from app.services.knowledge.models import (
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    require_scope,
    scope_allows,
    scope_of,
)
from app.services.knowledge.provider import (
    KnowledgeNotFoundError,
    SUPABASE_PROVIDER_ID,
)
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.object_storage import get_object

ObjectFetcher = Callable[[str, str], Awaitable[tuple[bytes, str]]]


def supabase_external_id(bucket: str, key: str) -> str:
    return f"{bucket}/{key}"


class SupabaseKnowledgeProvider:
    provider_id = SUPABASE_PROVIDER_ID

    def __init__(
        self,
        session: AsyncSession,
        vector_store: KnowledgeVectorStore,
        *,
        fetch_object: ObjectFetcher | None = None,
    ) -> None:
        self._session = session
        self._vector_store = vector_store
        self._fetch_object = fetch_object or get_object

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        require_scope(query.scope)
        raw_hits = await self._vector_store.search(query)
        allowed: list[KnowledgeHit] = []
        for hit in raw_hits:
            if hit.provider != self.provider_id:
                continue
            row = await self._row(hit.document_id)
            if row is None:
                continue
            if not self._visible(row, query.scope):
                continue
            allowed.append(
                KnowledgeHit(
                    document_id=row.document_id,
                    provider=row.provider,
                    title=hit.title or row.title,
                    excerpt=hit.excerpt,
                    score=hit.score,
                    locator=hit.locator,
                    external_id=row.external_id,
                    metadata={**dict(row.extra or {}), **hit.metadata},
                )
            )
            if len(allowed) >= query.limit:
                break
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

    async def _row(self, document_id: str) -> KnowledgeDocumentRecord | None:
        result = await self._session.execute(
            select(KnowledgeDocumentRecord).where(
                KnowledgeDocumentRecord.document_id == document_id
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
