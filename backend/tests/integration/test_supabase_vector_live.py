"""Opt-in live verification: document ingest → Supabase vector search."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import KnowledgeDocumentRecord, Kund
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.knowledge.ingest import KnowledgeIngestService
from app.services.knowledge.models import KnowledgeQuery, KnowledgeScope
from app.services.knowledge.supabase_provider import SupabaseKnowledgeProvider
from app.services.knowledge.supabase_vector_client import start_supabase_vector_runtime
from app.services.knowledge.vector_store import SupabaseVectorBucketStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_SUPABASE_VECTOR_INTEGRATION") != "1",
        reason="set RUN_SUPABASE_VECTOR_INTEGRATION=1 for live Supabase/OpenAI verification",
    ),
]


async def test_live_document_ingest_is_searchable():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    runtime = await start_supabase_vector_runtime(settings)
    store = SupabaseVectorBucketStore(runtime.client)
    document_id = f"integration-{uuid4()}"
    scope = KnowledgeScope(customer_id=1, module="expertgranskning")
    try:
        async with factory() as session:
            session.add(Kund(id=1, name="Integration", slug=f"integration-{uuid4()}"))
            session.add(
                KnowledgeDocumentRecord(
                    document_id=document_id,
                    provider="supabase",
                    external_id=f"integration/{document_id}.txt",
                    customer_id=1,
                    case_id=None,
                    module="expertgranskning",
                    title="Verifiering av kollektivavtal",
                    mime_type="text/plain",
                    storage_bucket="integration",
                    storage_key=f"{document_id}.txt",
                    version="1",
                    extra={"origin": "integration_test"},
                )
            )
            await session.commit()

            async def fetch_object(_bucket: str, _key: str) -> tuple[bytes, str]:
                return (
                    "Kollektivavtalet reglerar arbetstid och övertidsersättning.".encode(),
                    "text/plain",
                )

            embeddings = OpenAIEmbeddingProvider.from_settings()
            provider = SupabaseKnowledgeProvider(
                session,
                vector_store=store,
                embeddings=embeddings,
                fetch_object=fetch_object,
            )
            result = await KnowledgeIngestService(
                provider=provider,
                vector_store=store,
                embeddings=embeddings,
            ).ingest_document(document_id=document_id, scope=scope)
            assert result.status == "indexed"

            hits = await provider.search(
                KnowledgeQuery(query="Vad säger avtalet om övertid?", scope=scope, limit=3)
            )
            assert any(hit.document_id == document_id for hit in hits)
    finally:
        await store.delete_document(document_id)
        await runtime.close()
        await engine.dispose()
