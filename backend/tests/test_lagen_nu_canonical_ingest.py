"""lagen.nu documents enter the shared CanonicalDocument → TextUnit pipeline."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund, TextUnitRecord
from app.services.knowledge.persistence import (
    current_text_units,
    get_canonical_document_by_identity,
    get_current_document_version,
    list_document_versions,
)
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import (
    ingest_lagen_nu_document,
    lagen_nu_canonical_document_id,
    lagen_nu_source_identity,
)
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.registration import LAGEN_NU_PROVIDER_ID
from app.services.lagen_nu.uris import canonical_lagen_nu_document_uri
from tests.knowledge_fakes import FakeEmbeddingProvider

AVTALSLAGEN_URI = "https://lagen.nu/1915:218"
AVTALSLAGEN_TEXT = (
    "# 36 §\n\n"
    "Avtalsvillkor får jämkas eller lämnas utan avseende om villkoret är oskäligt.\n\n"
    "# 37 §\n\n"
    "Annat stycke om jämkning."
)
REVISED_TEXT = (
    "# 36 §\n\n"
    "Avtalsvillkor får jämkas när villkoret är oskäligt.\n\n"
    "# 37 §\n\n"
    "Annat stycke om jämkning."
)


def _document(
    *,
    uri: str = AVTALSLAGEN_URI,
    title: str = "Lag (1915:218) om avtal",
    text: str = AVTALSLAGEN_TEXT,
    pinpoint: str | None = "P36",
) -> LagenNuDocument:
    return LagenNuDocument(
        uri=uri,
        title=title,
        text=text,
        source="sfs",
        kind="lag",
        label="36 §",
        publisher_source_url="https://svenskforfattningssamling.se/1915:218",
        pinpoint=pinpoint,
        truncated=False,
        inbound_count=10,
    )


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _kund(session: AsyncSession) -> Kund:
    kund = Kund(name="acme", slug="acme", available_modules=["dd"])
    session.add(kund)
    await session.flush()
    return kund


def test_document_uri_strips_pinpoint_and_rewrites_ferenda():
    assert canonical_lagen_nu_document_uri("https://ferenda.lagen.nu/1915:218#P36") == (
        AVTALSLAGEN_URI
    )
    assert canonical_lagen_nu_document_uri("https://lagen.nu/1915:218#P37") == AVTALSLAGEN_URI
    assert canonical_lagen_nu_document_uri("http://lagen.nu/1981:130") == "https://lagen.nu/1981:130"
    assert canonical_lagen_nu_document_uri("https://lagen.nu/#P36") is None
    assert canonical_lagen_nu_document_uri("https://example.com/1915:218") is None


def test_source_identity_rejects_foreign_hosts():
    with pytest.raises(ValueError, match="canonical lagen.nu URI"):
        lagen_nu_source_identity(_document(uri="https://example.com/1915:218"))


def test_canonical_document_id_is_stable_per_customer_and_uri():
    first = lagen_nu_canonical_document_id(customer_id=1, canonical_uri=AVTALSLAGEN_URI)
    again = lagen_nu_canonical_document_id(customer_id=1, canonical_uri=AVTALSLAGEN_URI)
    other_customer = lagen_nu_canonical_document_id(customer_id=2, canonical_uri=AVTALSLAGEN_URI)
    other_uri = lagen_nu_canonical_document_id(
        customer_id=1,
        canonical_uri="https://lagen.nu/dom/nja/2005s142",
    )
    assert first == again
    assert first != other_customer
    assert first != other_uri
    assert len(first) == 64


async def test_ingest_creates_canonical_document_and_text_units(session: AsyncSession):
    kund = await _kund(session)
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    result = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(),
        embeddings=embeddings,
        vector_store=store,
    )
    await session.flush()
    expected_id = lagen_nu_canonical_document_id(
        customer_id=kund.id,
        canonical_uri=AVTALSLAGEN_URI,
    )
    row = await get_canonical_document_by_identity(
        session,
        customer_id=kund.id,
        source_type=LAGEN_NU_PROVIDER_ID,
        canonical_uri=AVTALSLAGEN_URI,
    )
    units = await current_text_units(session, expected_id)
    assert result.status == "indexed"
    assert result.reused_version is False
    assert result.document_id == expected_id
    assert result.content_hash == hash_text(AVTALSLAGEN_TEXT)
    assert row is not None
    assert row.id == expected_id
    assert row.source_type == LAGEN_NU_PROVIDER_ID
    assert row.canonical_uri == AVTALSLAGEN_URI
    assert row.title == "Lag (1915:218) om avtal"
    joined = "\n".join(unit.text for unit in units)
    assert len(units) >= 2
    assert "Avtalsvillkor får jämkas eller lämnas utan avseende om villkoret är oskäligt." in joined
    assert "Annat stycke om jämkning." in joined
    assert {item.chunk.document_id for item in store.chunks} == {expected_id}
    assert len(embeddings.calls) == 1


async def test_ingest_reuses_current_version_on_same_hash(session: AsyncSession):
    kund = await _kund(session)
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    first = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(pinpoint="P36"),
        embeddings=embeddings,
        vector_store=store,
    )
    second = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(uri=f"{AVTALSLAGEN_URI}#P37", pinpoint="P37"),
        embeddings=embeddings,
        vector_store=store,
    )
    await session.flush()
    documents = list((await session.execute(select(CanonicalDocumentRecord))).scalars().all())
    versions = await list_document_versions(session, first.document_id)
    units = list((await session.execute(select(TextUnitRecord))).scalars().all())
    assert first.document_id == second.document_id
    assert first.document_version_id == second.document_version_id
    assert second.reused_version is True
    assert len(documents) == 1
    assert documents[0].canonical_uri == AVTALSLAGEN_URI
    assert len(versions) == 1
    assert versions[0].content_hash == hash_text(AVTALSLAGEN_TEXT)
    assert len(units) == first.chunks_indexed
    assert len(embeddings.calls) == 1


async def test_ingest_new_version_on_content_change(session: AsyncSession):
    kund = await _kund(session)
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    first = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(),
        embeddings=embeddings,
        vector_store=store,
    )
    second = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(text=REVISED_TEXT),
        embeddings=embeddings,
        vector_store=store,
    )
    await session.flush()
    versions = await list_document_versions(session, first.document_id)
    current = await get_current_document_version(session, first.document_id)
    current_units = await current_text_units(session, first.document_id)
    historical = await session.get(TextUnitRecord, first.segmented.text_units[0].id)
    old_version = await session.get(DocumentVersionRecord, first.document_version_id)
    assert first.document_id == second.document_id
    assert first.document_version_id != second.document_version_id
    assert second.reused_version is False
    assert len(versions) == 2
    assert current is not None
    assert current.id == second.document_version_id
    assert current.content_hash == hash_text(REVISED_TEXT)
    assert current.superseded_at is None
    assert old_version is not None
    assert old_version.superseded_at is not None
    assert old_version.content_hash == hash_text(AVTALSLAGEN_TEXT)
    assert any("jämkas när villkoret" in unit.text for unit in current_units)
    assert historical is not None
    assert historical.document_version_id == first.document_version_id
    assert "lämnas utan avseende" in historical.text
    assert len(embeddings.calls) == 2


async def test_ingest_recurring_historical_hash_creates_new_occurrence(session: AsyncSession):
    kund = await _kund(session)
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    first = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(),
        embeddings=embeddings,
        vector_store=store,
    )
    second = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(text=REVISED_TEXT),
        embeddings=embeddings,
        vector_store=store,
    )
    first_after_change = await session.get(DocumentVersionRecord, first.document_version_id)
    assert first_after_change is not None
    first_superseded_at = first_after_change.superseded_at
    third = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(),
        embeddings=embeddings,
        vector_store=store,
    )
    await session.flush()
    first_again = await session.get(DocumentVersionRecord, first.document_version_id)
    second_after = await session.get(DocumentVersionRecord, second.document_version_id)
    current = await get_current_document_version(session, first.document_id)
    versions = await list_document_versions(session, first.document_id)
    first_units = list(
        (await session.execute(
            select(TextUnitRecord).where(
                TextUnitRecord.document_version_id == first.document_version_id
            )
        )).scalars().all()
    )
    third_units = list(
        (await session.execute(
            select(TextUnitRecord).where(
                TextUnitRecord.document_version_id == third.document_version_id
            )
        )).scalars().all()
    )
    assert len(versions) == 3
    assert third.reused_version is False
    assert first.document_version_id != third.document_version_id
    assert first_again is not None
    assert first_again.superseded_at == first_superseded_at
    assert first_again.content_hash == hash_text(AVTALSLAGEN_TEXT)
    assert second_after is not None
    assert second_after.superseded_at is not None
    assert current is not None
    assert current.id == third.document_version_id
    assert current.content_hash == hash_text(AVTALSLAGEN_TEXT)
    assert [row.content_hash for row in versions] == [
        hash_text(AVTALSLAGEN_TEXT),
        hash_text(REVISED_TEXT),
        hash_text(AVTALSLAGEN_TEXT),
    ]
    assert {row.id for row in first_units}.isdisjoint({row.id for row in third_units})
    assert len(embeddings.calls) == 3


async def test_empty_text_is_empty_status_without_persist(session: AsyncSession):
    kund = await _kund(session)
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    result = await ingest_lagen_nu_document(
        session,
        customer_id=kund.id,
        document=_document(text="   \n"),
        embeddings=embeddings,
        vector_store=store,
    )
    await session.flush()
    documents = list((await session.execute(select(CanonicalDocumentRecord))).scalars().all())
    assert result.status == "empty"
    assert result.chunks_indexed == 0
    assert documents == []
    assert embeddings.calls == []
    assert store.chunks == []
