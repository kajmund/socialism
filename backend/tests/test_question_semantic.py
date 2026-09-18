from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import KnowledgeQuestionRow, Kund
from app.services.knowledge.models import EmbeddedKnowledgeChunk, KnowledgeChunk
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.research.knowledge_question import (
    identity_from_text,
    tenant_question_scope,
)
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.question_semantic import SemanticQuestionIdentityMatcher


class MeaningEmbeddingProvider:
    provider_id = "test"
    model = "test-meaning"
    dimension = 3

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            normalized = text.casefold()
            if "jämk" in normalized or "oskälig" in normalized:
                vectors.append([1.0, 0.0, 0.0])
            elif "häv" in normalized or "upphör" in normalized:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


@pytest.fixture
async def factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add_all(
            [
                Kund(name="Acme", slug="acme", available_modules=[]),
                Kund(name="Other", slug="other", available_modules=[]),
            ]
        )
        await session.commit()
    yield session_factory
    await engine.dispose()


def _graph(store: MemoryKnowledgeVectorStore, *, limit: int = 5) -> SqlQuestionEvidenceGraph:
    return SqlQuestionEvidenceGraph(
        matcher=SemanticQuestionIdentityMatcher(
            vector_store=store,
            embeddings=MeaningEmbeddingProvider(),
            version="test-v1",
            threshold=0.8,
            limit=limit,
        )
    )


async def test_semantic_question_match_reuses_canonical_identity(factory):
    store = MemoryKnowledgeVectorStore()
    graph = _graph(store)
    async with factory() as session:
        first = await graph.upsert_question(
            session,
            identity_from_text("När får ett avtal jämkas enligt 36 § avtalslagen?"),
            tenant_question_scope(1),
        )
        second = await graph.upsert_question(
            session,
            identity_from_text("Vilka rekvisit gör ett avtalsvillkor oskäligt?"),
            tenant_question_scope(1),
        )
        count = await session.scalar(select(func.count()).select_from(KnowledgeQuestionRow))
        stored = await session.get(KnowledgeQuestionRow, first.id)

    assert second.id == first.id
    assert count == 1
    assert stored is not None
    assert (
        stored.embedding_model,
        stored.embedding_version,
        stored.embedding_dimension,
    ) == ("test-meaning", "test-v1", 3)


async def test_semantic_question_match_keeps_different_meanings_separate(factory):
    store = MemoryKnowledgeVectorStore()
    graph = _graph(store)
    async with factory() as session:
        first = await graph.upsert_question(
            session,
            identity_from_text("När får ett avtal jämkas?"),
            tenant_question_scope(1),
        )
        second = await graph.upsert_question(
            session,
            identity_from_text("När får en part häva avtalet?"),
            tenant_question_scope(1),
        )

    assert second.id != first.id


async def test_semantic_question_match_never_crosses_customer_namespace(factory):
    store = MemoryKnowledgeVectorStore()
    graph = _graph(store)
    async with factory() as session:
        first = await graph.upsert_question(
            session,
            identity_from_text("När får ett avtal jämkas?"),
            tenant_question_scope(1),
        )
        second = await graph.upsert_question(
            session,
            identity_from_text("Vilka villkor är oskäliga?"),
            tenant_question_scope(2),
        )

    assert second.id != first.id
    assert second.scope.namespace == "tenant:2"


async def test_semantic_question_search_isolated_from_document_vectors(factory):
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [
            EmbeddedKnowledgeChunk(
                chunk=KnowledgeChunk(
                    document_id="document-1",
                    chunk_id="chunk-1",
                    text="När får ett avtal jämkas?",
                    customer_id=-1,
                    case_id=None,
                    module=None,
                    title="Dokument",
                    metadata={"knowledge_kind": "document"},
                ),
                embedding=[1.0, 0.0, 0.0],
            )
        ]
    )
    graph = _graph(store, limit=1)
    async with factory() as session:
        first = await graph.upsert_question(
            session,
            identity_from_text("När får ett avtal jämkas?"),
            tenant_question_scope(1),
        )
        second = await graph.upsert_question(
            session,
            identity_from_text("Vilka avtalsvillkor är oskäliga?"),
            tenant_question_scope(1),
        )

    assert second.id == first.id
