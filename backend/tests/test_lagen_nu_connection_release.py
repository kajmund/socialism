"""External research boundaries work with a single database connection."""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import ingest_lagen_nu_document
from app.services.lagen_nu.models import SearchResults
from app.services.lagen_nu.passage_router import KeepAllPassageRouter
from app.services.lagen_nu.research_source import LagenNuResearchSource
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_lagen_nu_provider import (
    FakeLagenNuClient,
    FakeLegalInterpreter,
    PassthroughLagenNuSelector,
    _document,
    _hit,
)
from tests.test_research import _context, _need

URI = "https://lagen.nu/1915:218"


@pytest.fixture
async def single_connection(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'research.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory.begin() as session:
        session.add(Kund(id=7, name="acme", slug="acme", available_modules=["dd"]))
    try:
        yield engine, factory
    finally:
        await engine.dispose()


async def _probe(factory):
    # Model/cache providers need to be able to acquire a connection independently.
    async with factory() as session:
        assert await session.scalar(select(Kund.id).where(Kund.id == 7)) == 7


class _ProbingEmbeddings(FakeEmbeddingProvider):
    def __init__(self, factory):
        super().__init__()
        self.factory = factory

    async def embed(self, texts):
        await _probe(self.factory)
        return await super().embed(texts)


class _ProbingPassageRouter(KeepAllPassageRouter):
    def __init__(self, factory):
        self.factory = factory
        self.calls = 0

    async def route(self, **kwargs):
        await _probe(self.factory)
        self.calls += 1
        return await super().route(**kwargs)


@pytest.mark.parametrize("warm_first", [False, True])
async def test_four_cached_needs_leave_connection_available_during_routing(
    single_connection, warm_first
):
    engine, factory = single_connection
    embeddings = _ProbingEmbeddings(factory)
    store = MemoryKnowledgeVectorStore()
    client = FakeLagenNuClient(
        search=SearchResults(query="", total=1, results=(_hit(uri=URI, pinpoint=None),)),
        documents={
            URI: _document(uri=URI, pinpoint=None, text="Oskäliga avtalsvillkor får jämkas.")
        },
    )
    router = _ProbingPassageRouter(factory)

    async def research(index):
        async with factory() as session:
            source = LagenNuResearchSource(
                source_type="swedish_law",
                client=client,
                selector=PassthroughLagenNuSelector(),
                interpreter=FakeLegalInterpreter(),
                session=session,
                embeddings=embeddings,
                vector_store=store,
                passage_router=KeepAllPassageRouter() if warm_first and index == 0 else router,
            )
            return await source.research(
                _need("swedish_law", question=f"När får oskäliga avtalsvillkor jämkas? {index}"),
                _context(),
            )

    warm = await research(0)
    assert [item.status for item in warm] == ["found"]
    batches = await asyncio.gather(*(research(index) for index in range(1, 5)))
    assert [[item.status for item in batch] for batch in batches] == [["found"]] * 4
    assert all(batch[0].metadata["reused_text_units"] for batch in batches)
    assert router.calls == (4 if warm_first else 5)
    assert len([name for name, _ in client.calls if name == "get_document"]) == 1
    assert engine.pool.checkedout() == 0


async def test_reused_version_releases_connection_before_reindex_embedding(single_connection):
    engine, factory = single_connection
    embeddings = _ProbingEmbeddings(factory)
    document = _document(uri=URI, pinpoint=None, text="Oskäliga avtalsvillkor får jämkas.")
    async with factory() as session:
        first = await ingest_lagen_nu_document(
            session,
            customer_id=7,
            document=document,
            embeddings=embeddings,
            vector_store=MemoryKnowledgeVectorStore(),
        )
        # A new index has no vectors, while SQL still has the same document version.
        second = await ingest_lagen_nu_document(
            session,
            customer_id=7,
            document=document,
            embeddings=embeddings,
            vector_store=MemoryKnowledgeVectorStore(),
        )
    assert second.document_version_id == first.document_version_id
    assert second.reused_version is True
    assert len(embeddings.calls) == 2
    assert engine.pool.checkedout() == 0
