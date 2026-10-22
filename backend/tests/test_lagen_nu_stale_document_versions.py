"""A stale SQL DocumentVersion without graph TextUnits must be re-ingested."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import (
    lagen_nu_canonical_document_id,
    lagen_nu_source_identity,
)
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.text_unit_research import (
    current_lagen_nu_units,
    ingest_and_load_text_units,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.text_units import load_domain_text_units

CUSTOMER_ID = 1
DOCUMENT = LagenNuDocument(
    uri="https://lagen.nu/1915:218",
    title="Lag (1915:218) om avtal",
    text="## 36 §\n\nAvtalsvillkor får jämkas eller lämnas utan avseende.",
    source="sfs",
    kind="lag",
    label="36 §",
    publisher_source_url="https://svenskforfattningssamling.se/1915:218",
    pinpoint="P36",
    truncated=False,
    inbound_count=10,
)


class _Embeddings:
    provider_id = "stale-test"
    model = "stale-test-embedding"
    dimension = 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as database:
        yield database
    await engine.dispose()


async def _stale_document(session: AsyncSession) -> str:
    canonical_uri = lagen_nu_source_identity(DOCUMENT)
    document_id = lagen_nu_canonical_document_id(
        canonical_uri=canonical_uri, customer_id=CUSTOMER_ID
    )
    session.add(
        CanonicalDocumentRecord(
            id=document_id,
            customer_id=CUSTOMER_ID,
            source_type="lagen_nu",
            canonical_uri=canonical_uri,
            title=DOCUMENT.title or canonical_uri,
            extra={},
        )
    )
    session.add(
        DocumentVersionRecord(
            id="stale-version",
            document_id=document_id,
            customer_id=CUSTOMER_ID,
            content_hash=hash_text(DOCUMENT.text),
            mime_type="text/plain",
            extra={},
        )
    )
    await session.flush()
    return canonical_uri


async def test_stale_sql_version_without_graph_units_is_not_ingested(
    session: AsyncSession,
) -> None:
    canonical_uri = await _stale_document(session)
    assert await current_lagen_nu_units(
        session, customer_id=CUSTOMER_ID, canonical_uri=canonical_uri
    ) is None


async def test_reingest_replaces_stale_version_and_writes_text_units(
    session: AsyncSession,
) -> None:
    canonical_uri = await _stale_document(session)
    result, units = await ingest_and_load_text_units(
        session,
        customer_id=CUSTOMER_ID,
        document=DOCUMENT,
        embeddings=_Embeddings(),
        vector_store=MemoryKnowledgeVectorStore(),
    )

    assert result.status == "indexed"
    assert units
    assert await current_lagen_nu_units(
        session, customer_id=CUSTOMER_ID, canonical_uri=canonical_uri
    )
    assert load_domain_text_units(
        require_knowledge(), document_version_id=result.document_version_id or ""
    )
