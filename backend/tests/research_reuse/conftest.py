import socket
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund
from tests.test_research_graph_v2_reuse import Embeddings, seed_fact


@pytest.fixture(autouse=True)
def offline_boundaries(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise RuntimeError("research_reuse CI tests must mock every network boundary")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr("app.services.research.composition.research_embeddings", Embeddings)


@pytest.fixture
async def reuse_db(tmp_path, research_overgraph):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'reuse.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.5,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory.begin() as session:
        session.add_all(
            [Kund(id=1, name="First", slug="first"), Kund(id=2, name="Other", slug="other")]
        )
    yield factory
    await engine.dispose()


@pytest.fixture
async def graph_basis(reuse_db, research_overgraph):
    async with reuse_db.begin() as session:
        await seed_fact(session)
    return reuse_db


@pytest.fixture
def no_source_work(monkeypatch):
    calls = {}
    boundaries = {
        "fetch": "app.services.lagen_nu.mcp_client.OfficialLagenNuMcpClient.get_document",
        "ingest": "app.services.lagen_nu.text_unit_research.ingest_lagen_nu_document",
        "index": "app.services.knowledge.supabase_vector_client.SupabaseStorageVectorClient.upsert",
        "ttl": "app.services.knowledge.answer_review_classification.classify_pending_reviews",
    }
    for label, path in boundaries.items():
        calls[label] = AsyncMock(side_effect=AssertionError(f"Unexpected {label}"))
        monkeypatch.setattr(path, calls[label])
    calls["chunk"] = Mock(side_effect=AssertionError("Unexpected chunking"))
    monkeypatch.setattr("app.services.knowledge.chunking.KnowledgeChunker.segment", calls["chunk"])
    return calls


@pytest.fixture
def result_jev(monkeypatch, reuse_db):
    from tests.research_reuse.result_helpers import mock_result_jev
    return mock_result_jev(monkeypatch, reuse_db)
