"""Opt-in PostgreSQL verification in disposable schemas, also required in CI."""

import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, TextUnitRecord
from app.database.text_units import SharedTextChunkRecord
from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
from app.services.knowledge.shared_chunks import resolve_shared_chunks
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import ingest_lagen_nu_document
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_lagen_nu_canonical_ingest import _document
from tests.test_shared_chunk_migration import seed

POSTGRES_URL = os.environ.get("TEST_SHARED_CHUNK_POSTGRES_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not POSTGRES_URL, reason="PG opt-in")]


@pytest.fixture
def pg_database():
    schema = "shared_chunks_test_" + uuid4().hex
    admin = sa.create_engine(POSTGRES_URL)
    engine = sa.create_engine(POSTGRES_URL, connect_args={"options": f"-csearch_path={schema}"})
    with admin.begin() as connection:
        connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
    try:
        yield engine, schema
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def test_postgres_migration_protects_shared_content_and_preserves_provenance(pg_database, monkeypatch):
    engine, _schema = pg_database
    path = Path(__file__).parents[1] / "alembic/versions/e8c2f4a1b6d0_shared_text_chunks.py"
    spec = importlib.util.spec_from_file_location("pg_shared_chunk_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.execute(sa.text("""CREATE TABLE text_units (
            id VARCHAR(64) PRIMARY KEY, text TEXT NOT NULL, content_hash VARCHAR(64) NOT NULL,
            document_version_id TEXT NOT NULL, locator TEXT, scope_key TEXT, valid_to TEXT
        )"""))
        connection.execute(sa.text("""CREATE TABLE support (
            id INTEGER PRIMARY KEY, unit_id TEXT REFERENCES text_units(id) ON DELETE CASCADE
        )"""))
        seed(connection)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.scalar(sa.text("SELECT count(*) FROM shared_text_chunks")) == 1
        assert connection.execute(sa.text("SELECT * FROM support ORDER BY id")).all() == [(1,"a"),(2,"b")]
        assert connection.scalar(sa.text("SELECT relrowsecurity FROM pg_class WHERE oid='shared_text_chunks'::regclass"))
        assert connection.scalar(sa.text("SELECT count(*) FROM pg_policy WHERE polrelid='shared_text_chunks'::regclass")) == 0
        with pytest.raises(sa.exc.DatabaseError, match="immutable"), connection.begin_nested():
            connection.execute(sa.text("UPDATE shared_text_chunks SET text='Changed'"))
        connection.execute(sa.text("INSERT INTO shared_text_chunks VALUES (:hash,'New')"), {"hash": hash_text("New")})
        with pytest.raises(sa.exc.DatabaseError, match="immutable"), connection.begin_nested():
            connection.execute(sa.text("UPDATE text_units SET content_hash=:hash WHERE id='a'"), {"hash": hash_text("New")})
        migration.downgrade()
        assert connection.scalar(sa.text("SELECT count(*) FROM support")) == 2
        assert set(connection.scalars(sa.text("SELECT text FROM text_units"))) == {"Åäö. Exakt  text."}


async def test_postgres_ingestion_and_concurrent_shared_chunk_resolution(pg_database):
    _sync_engine, schema = pg_database
    engine = create_async_engine(POSTGRES_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as session:
            session.add(Kund(id=1, name="Test", slug="test"))
        inner, store = FakeEmbeddingProvider(), MemoryKnowledgeVectorStore()
        for uri in ("https://lagen.nu/1915:218", "https://lagen.nu/1981:130"):
            async with factory() as session:
                await ingest_lagen_nu_document(
                    session, customer_id=1, document=_document(uri=uri, text="Exakt Åäö."),
                    embeddings=GraphEmbeddingCacheProvider(factory, inner), vector_store=store,
                )
        async with factory() as session:
            assert len(list(await session.scalars(sa.select(SharedTextChunkRecord)))) == 1
            assert len(list(await session.scalars(sa.select(TextUnitRecord)))) == 2
            assert len(inner.calls) == 1
        await _concurrent_resolution(factory)
    finally:
        await engine.dispose()


async def _concurrent_resolution(factory):
    async def write(order):
        async with factory.begin() as session:
            chunks = await resolve_shared_chunks(session, [(hash_text(value), value) for value in order])
            return set(chunks)

    first, second = await asyncio.wait_for(asyncio.gather(
        write(["Concurrent A", "Concurrent B"]), write(["Concurrent B", "Concurrent A"]),
    ), timeout=5)
    assert first == second == {hash_text("Concurrent A"), hash_text("Concurrent B")}
