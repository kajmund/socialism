"""Real ingest/SQL/cache: exact chunk SHA reuse with external boundaries mocked."""

from dataclasses import dataclass
import asyncio
import unicodedata
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text

from app.database.graph_v2 import GraphEmbeddingCache
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, TextUnitRecord
from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider, _cache_identity
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import ingest_lagen_nu_document
from tests.knowledge_fakes import FakeEmbeddingProvider, fake_embed_text
from tests.test_lagen_nu_canonical_ingest import _document

URI_A = "https://lagen.nu/1915:218"
URI_B = "https://lagen.nu/1981:130"
TEXT = "# Gemensam text\n\nÅteranvänd denna text med Ö och å."
pytestmark = pytest.mark.research_reuse


async def available_connection(factory):
    async with factory() as session:
        assert await session.scalar(text("SELECT 1")) == 1


class Embedder(FakeEmbeddingProvider):
    model_revision = "revision-a"

    async def embed(self, texts):
        self.calls.append(tuple(texts))
        return [fake_embed_text(text, dimension=self.dimension) for text in texts]


@dataclass
class Lab:
    factory: object
    store: MemoryKnowledgeVectorStore
    inner: Embedder

    async def ingest(self, uri, text=TEXT, inner=None):
        inner = inner or self.inner
        # New cache instance every time: verify durable reuse, not process memory.
        provider = GraphEmbeddingCacheProvider(self.factory, inner)
        async with self.factory() as session:
            result = await ingest_lagen_nu_document(
                session, customer_id=1, document=_document(uri=uri, text=text, pinpoint=None),
                embeddings=provider, vector_store=self.store,
            )
            await session.commit()
        return result

    async def rows(self, model):
        async with self.factory() as session:
            return list(await session.scalars(select(model)))


@pytest.fixture
async def lab(reuse_db):
    inner = Embedder()
    original_embed = inner.embed

    async def embed(texts):
        await available_connection(reuse_db)
        return await original_embed(texts)

    inner.embed = AsyncMock(side_effect=embed)
    store = MemoryKnowledgeVectorStore()
    original_upsert = store.upsert_chunks

    async def upsert(chunks):
        await available_connection(reuse_db)
        return await original_upsert(chunks)

    store.upsert_chunks = AsyncMock(side_effect=upsert)
    return Lab(reuse_db, store, inner)


async def test_identical_chunks_reuse_embedding_but_preserve_both_sources(lab):
    first = await lab.ingest(URI_A)
    before = list(lab.inner.calls)
    lab.inner.embed.side_effect = AssertionError("Identical chunk embedded again")
    second = await lab.ingest(URI_B)
    assert first.document_id != second.document_id
    assert first.document_version_id != second.document_version_id
    assert lab.inner.calls == before
    assert len(await lab.rows(GraphEmbeddingCache)) == 1
    documents = await lab.rows(CanonicalDocumentRecord)
    versions = await lab.rows(DocumentVersionRecord)
    units = await lab.rows(TextUnitRecord)
    assert {row.canonical_uri for row in documents} == {URI_A, URI_B}
    assert len(versions) == 2 and all(row.superseded_at is None for row in versions)
    assert len(units) == 2 and len({row.content_hash for row in units}) == 1
    assert all(row.content_hash == hash_text(row.text) for row in units)
    projections = lab.store.chunks
    assert {item.chunk.document_id for item in projections} == {first.document_id, second.document_id}
    assert len(projections) == 2 and projections[0].embedding == projections[1].embedding


async def test_embedding_cache_hash_is_the_exact_chunk_sha(lab):
    await lab.ingest(URI_A)
    units = await lab.rows(TextUnitRecord)
    rows = await lab.rows(GraphEmbeddingCache)
    assert {row.normalized_text_hash for row in rows} == {row.content_hash for row in units}


async def test_embedding_service_receives_exact_chunk_text(lab):
    result = await lab.ingest(URI_A)
    assert lab.inner.calls == [tuple(unit.text for unit in result.segmented.text_units)]


@pytest.mark.parametrize("changed", ["case", "spacing", "punctuation", "unicode"])
async def test_different_chunk_sha_never_reuses_the_same_embedding_entry(lab, changed):
    first = await lab.ingest(URI_A)
    variants = {
        "case": TEXT.lower(),
        "spacing": TEXT.replace("denna text", "denna  text"),
        "punctuation": TEXT[:-1] + "!",
        "unicode": unicodedata.normalize("NFD", TEXT),
    }
    second = await lab.ingest(URI_B, variants[changed])
    assert first.segmented.text_units[0].content_hash != second.segmented.text_units[0].content_hash
    assert len(lab.inner.calls) == 2
    assert len(await lab.rows(GraphEmbeddingCache)) == 2


@pytest.mark.parametrize("change", ["model", "model_revision", "dimension"])
async def test_same_chunk_sha_cannot_reuse_an_incompatible_representation(lab, change):
    await lab.ingest(URI_A)
    other = Embedder()
    setattr(other, change, 16 if change == "dimension" else "another")
    await lab.ingest(URI_B, inner=other)
    assert len(lab.inner.calls) == 1 and len(other.calls) == 1
    assert len(await lab.rows(GraphEmbeddingCache)) == 2


async def test_only_new_chunks_are_embedded_in_a_partially_overlapping_document(lab):
    first = await lab.ingest(URI_A, TEXT + "\n\n# A\n\nBara det första dokumentet.")
    second = await lab.ingest(URI_B, TEXT + "\n\n# B\n\nBara det andra dokumentet.")
    assert len(lab.inner.calls) == 2
    assert len(lab.inner.calls[0]) == 2 and len(lab.inner.calls[1]) == 1
    common = set(unit.content_hash for unit in first.segmented.text_units) & set(
        unit.content_hash for unit in second.segmented.text_units
    )
    assert len(common) == 1
    assert len(await lab.rows(GraphEmbeddingCache)) == 3


async def test_changed_text_does_not_overwrite_the_other_document(lab):
    first = await lab.ingest(URI_A)
    await lab.ingest(URI_B)
    changed = await lab.ingest(URI_B, TEXT + " Ändrad regel.")
    assert len(lab.inner.calls) == 2
    versions = await lab.rows(DocumentVersionRecord)
    first_version = next(row for row in versions if row.id == first.document_version_id)
    assert first_version.superseded_at is None
    assert first_version.content_hash == hash_text(TEXT)
    assert changed.document_id != first.document_id
    units = await lab.rows(TextUnitRecord)
    assert next(row for row in units if row.document_id == first.document_id).text == TEXT


async def test_old_normalized_cache_is_never_used_as_an_exact_text_fallback(lab):
    text_value = "already normalized text"
    key, digest = _cache_identity(
        (lab.inner.model, lab.inner.model_revision, lab.inner.dimension, "text.v1"), text_value,
    )
    async with lab.factory.begin() as session:
        session.add(GraphEmbeddingCache(
            key=key, model=lab.inner.model, model_revision=lab.inner.model_revision,
            dimension=lab.inner.dimension, purpose="text.v1", normalized_text_hash=digest,
            vector=[777.0] * lab.inner.dimension, status="ready",
        ))
    await lab.ingest(URI_A, text_value)
    assert lab.inner.calls == [(text_value,)]
    assert len(await lab.rows(GraphEmbeddingCache)) == 2
    assert lab.store.chunks[0].embedding != [777.0] * lab.inner.dimension


@pytest.mark.parametrize("failure", [RuntimeError("embedding failed"), asyncio.CancelledError()])
async def test_embedding_failure_releases_connection_and_lease_without_indexing(lab, failure):
    async def fail(_texts):
        await available_connection(lab.factory)
        raise failure

    lab.inner.embed.side_effect = fail
    with pytest.raises(type(failure)):
        await lab.ingest(URI_A)
    await available_connection(lab.factory)
    rows = await lab.rows(GraphEmbeddingCache)
    assert len(rows) == 1 and rows[0].status == "pending"
    assert rows[0].lock_owner is None and rows[0].lock_expires_at is None
    lab.store.upsert_chunks.assert_not_awaited()
