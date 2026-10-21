"""Opt-in PostgreSQL verification of OverGraph-backed ingestion, also required in CI."""

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund
from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import ingest_lagen_nu_document
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.text_units import count_text_units
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_lagen_nu_canonical_ingest import _document

POSTGRES_URL = os.environ.get("TEST_SHARED_CHUNK_POSTGRES_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not POSTGRES_URL, reason="PG opt-in")]


@pytest.fixture
def pg_schema():
    schema = "overgraph_ingest_" + uuid4().hex
    admin = sa.create_engine(POSTGRES_URL)
    with admin.begin() as connection:
        connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
    try:
        yield schema
    finally:
        with admin.begin() as connection:
            connection.execute(sa.text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


async def test_postgres_ingestion_keeps_two_occurrences_and_reuses_one_embedding(pg_schema):
    engine = create_async_engine(
        POSTGRES_URL, connect_args={"options": f"-csearch_path={pg_schema}"},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as session:
            session.add(Kund(id=1, name="Test", slug="test"))
        before = count_text_units(require_knowledge())
        inner, store = FakeEmbeddingProvider(), MemoryKnowledgeVectorStore()
        for uri in ("https://lagen.nu/1915:218", "https://lagen.nu/1981:130"):
            async with factory() as session:
                await ingest_lagen_nu_document(
                    session,
                    customer_id=1,
                    document=_document(uri=uri, text="Exakt Åäö."),
                    embeddings=GraphEmbeddingCacheProvider(factory, inner),
                    vector_store=store,
                )
        assert count_text_units(require_knowledge()) == before + 2
        assert len(inner.calls) == 1
    finally:
        await engine.dispose()
