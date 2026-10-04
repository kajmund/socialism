"""Supabase discovery; SQL validates every original document passage."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import KnowledgeDocumentRecord, StoredObject
from app.database.transaction_state import has_pending_writes
from app.services.knowledge.document_grounding import grounded_hits, source_visible, validate_manifest
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.models import (
    EmbeddedKnowledgeQuery,
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    require_scope,
    scope_of,
)
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID, KnowledgeNotFoundError
from app.services.knowledge.shared_document_grounding import grounded_shared_hits
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
        self._factory = async_sessionmaker(session.bind, expire_on_commit=False)
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._fetch_object = fetch_object or get_object

    @property
    def shared_db_session(self) -> AsyncSession:
        return self._session

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        require_scope(query.scope)
        await self._release_reader()
        async with self._factory() as session:
            if query.filters.get("scope_type") != "shared":
                await validate_manifest(session, query.scope)
        vectors = await self._embeddings.embed([query.query])
        if len(vectors) != 1:
            raise RuntimeError(f"EmbeddingProvider returned {len(vectors)} vectors for 1 query")
        allowed: list[KnowledgeHit] = []
        seen: dict[str, int] = {}
        fetch_limit = query.limit
        max_fetch = query.limit * _SEARCH_OVERFETCH_FACTOR
        while len(allowed) < query.limit:
            raw_hits = await self._vector_store.search(
                EmbeddedKnowledgeQuery(
                    query=KnowledgeQuery(query=query.query, scope=query.scope, limit=fetch_limit, filters=query.filters),
                    embedding=vectors[0],
                )
            )
            passages = await self._ground(raw_hits, query)
            for passage in passages:
                unit_id = str(passage.metadata["text_unit_id"])
                if unit_id not in seen:
                    seen[unit_id] = len(allowed)
                    allowed.append(passage)
                elif passage.metadata.get("discovery_kind") == "document_item":
                    allowed[seen[unit_id]] = passage
            if len(raw_hits) < fetch_limit or fetch_limit >= max_fetch:
                break
            fetch_limit = min(fetch_limit * 2, max_fetch)
        return allowed[:query.limit]

    async def _ground(self, hits: list[KnowledgeHit], query: KnowledgeQuery) -> list[KnowledgeHit]:
        async with self._factory() as session:
            passages = []
            for hit in hits:
                if query.filters.get("scope_type") == "shared":
                    passages.extend(await grounded_shared_hits(session, hit))
                elif hit.provider == self.provider_id:
                    passages.extend(await grounded_hits(session, hit, query.scope))
            return passages

    async def get_document(self, document_id: str, scope: KnowledgeScope) -> KnowledgeDocument | None:
        require_scope(scope)
        await self._release_reader()
        async with self._factory() as session:
            row = await self._row(session, document_id)
            if row is None or not await self._visible(session, row, scope):
                return None
            return await self._to_document(session, row)

    async def fetch_content(self, document_id: str, scope: KnowledgeScope) -> bytes:
        require_scope(scope)
        await self._release_reader()
        async with self._factory() as session:
            row = await self._row(session, document_id)
            if row is None or not await self._visible(session, row, scope):
                raise KnowledgeNotFoundError(document_id)
            bucket, key = row.storage_bucket, row.storage_key
        if not bucket or not key:
            raise KnowledgeNotFoundError(document_id)
        data, _content_type = await self._fetch_object(bucket, key)
        return data

    async def _release_reader(self) -> None:
        if has_pending_writes(self._session):
            raise RuntimeError("Knowledge external work requires a clean input transaction")
        if self._session.in_transaction():
            await self._session.rollback()

    async def _row(self, session: AsyncSession, document_id: str) -> KnowledgeDocumentRecord | None:
        return await session.scalar(select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.document_id == document_id,
            KnowledgeDocumentRecord.provider == self.provider_id,
        ))

    @staticmethod
    async def _visible(session: AsyncSession, row: KnowledgeDocumentRecord, scope: KnowledgeScope) -> bool:
        if row.source_object_id is not None:
            source = await session.get(StoredObject, row.source_object_id)
            return source is not None and source_visible(source, scope)
        return False

    @staticmethod
    async def _to_document(session: AsyncSession, row: KnowledgeDocumentRecord) -> KnowledgeDocument:
        source = await session.get(StoredObject, row.source_object_id) if row.source_object_id else None
        metadata = dict(row.extra or {})
        if source is not None:
            metadata.update({"workspace_id": source.workspace_id, "source_object_id": source.id})
        return KnowledgeDocument(
            document_id=row.document_id,
            provider=row.provider,
            external_id=row.external_id,
            title=row.title,
            mime_type=row.mime_type,
            scope=scope_of(customer_id=row.customer_id, case_id=row.case_id, module=row.module, workspace_id=metadata.get("workspace_id")),
            version=row.version,
            metadata=metadata,
        )
