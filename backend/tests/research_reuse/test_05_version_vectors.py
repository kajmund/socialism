"""Canonical source indexing preserves temporal vectors without inventory scans."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from storage3.types import VectorMatch

from app.database.models import DocumentVersionRecord, Kund
from app.services.knowledge.canonical_ingest import index_missing_persisted_documents
from app.services.knowledge.persistence import current_text_units, text_units_for_version
from app.services.knowledge.supabase_vector_client import SupabaseStorageVectorClient
from app.services.knowledge.vector_store import SupabaseVectorBucketStore
from tests.research_reuse.test_03_chunk_sha import (
    TEXT, URI_A, available_connection, lab as lab,
)

pytestmark = pytest.mark.research_reuse


class VersionIndex:
    """Live transport adapter with only its SDK/network boundary replaced."""

    def __init__(self, factory):
        self.factory = factory
        self.vectors = {}
        self.puts = []
        self.gets = []
        self.failure = None
        self.partial_failure = False

    async def put(self, vectors):
        await available_connection(self.factory)
        if self.failure is not None:
            failure, self.failure = self.failure, None
            if self.partial_failure:
                self.vectors[vectors[0].key] = vectors[0]
            raise failure
        self.puts.append([vector.key for vector in vectors])
        self.vectors.update({vector.key: vector for vector in vectors})

    async def get(self, *keys, **_kwargs):
        await available_connection(self.factory)
        self.gets.append(keys)
        return SimpleNamespace(vectors=[
            VectorMatch(key=key, data=self.vectors[key].data, metadata=self.vectors[key].metadata)
            for key in keys if key in self.vectors
        ])

    async def list(self, **_kwargs):
        raise AssertionError("Source indexing must not scan the vector index")

    async def delete(self, *_args):
        raise AssertionError("Source indexing must preserve historical vectors")

    async def query(self, *_args, **_kwargs):
        raise AssertionError("Known TextUnits must be retrieved by exact keys")


@pytest.fixture
def projected(lab):
    index = VersionIndex(lab.factory)
    lab.store = SupabaseVectorBucketStore(SupabaseStorageVectorClient(index))
    return lab, index


async def vectors_for(lab, result):
    async with lab.factory() as session:
        unit_ids = [row.id for row in await text_units_for_version(session, result.document_version_id)]
    return await lab.store.get_text_unit_embeddings(
        document_id=result.document_id, document_version_id=result.document_version_id,
        text_unit_ids=unit_ids,
    )


async def test_cold_source_indexing_only_writes_its_known_projection_keys(projected):
    lab, index = projected
    result = await lab.ingest(URI_A)
    assert len(index.puts) == 1 and index.gets == []
    assert len(index.vectors) == result.chunks_indexed
    stored = next(iter(index.vectors.values()))
    assert stored.metadata["document_version_id"] == result.document_version_id
    assert stored.metadata["text_unit_id"] == result.segmented.text_units[0].id


async def test_a_b_a_keeps_all_three_versions_addressable_by_exact_keys(projected):
    lab, index = projected
    first = await lab.ingest(URI_A)
    original = dict(index.vectors)
    second = await lab.ingest(URI_A, TEXT + " Ny regel.")
    third = await lab.ingest(URI_A)
    assert len(index.vectors) == sum(item.chunks_indexed for item in (first, second, third))
    assert all(index.vectors[key] == value for key, value in original.items())
    first_vectors = await vectors_for(lab, first)
    assert await vectors_for(lab, second)
    third_vectors = await vectors_for(lab, third)
    assert list(first_vectors.values()) == list(third_vectors.values())
    assert set(first_vectors).isdisjoint(third_vectors)
    assert len(lab.inner.calls) == 2
    async with lab.factory() as session:
        current = await current_text_units(session, third.document_id)
    assert {row.document_version_id for row in current} == {third.document_version_id}


async def test_warm_current_version_reads_exact_keys_without_embedding_or_writing(projected):
    lab, index = projected
    first = await lab.ingest(URI_A)
    before = dict(index.vectors)
    second = await lab.ingest(URI_A)
    assert second.reused_version and second.document_version_id == first.document_version_id
    assert index.vectors == before and len(index.puts) == 1
    assert len(index.gets) == 1 and len(index.gets[0]) == first.chunks_indexed
    assert len(lab.inner.calls) == 1


@pytest.mark.parametrize("failure", [RuntimeError("index unavailable"), asyncio.CancelledError()])
async def test_failed_new_projection_keeps_history_and_retry_reuses_cache(projected, failure):
    lab, index = projected
    first = await lab.ingest(URI_A)
    before = dict(index.vectors)
    index.failure = failure
    with pytest.raises(type(failure)):
        await lab.ingest(URI_A, TEXT + " Ny regel.")
    assert index.vectors == before
    await available_connection(lab.factory)
    retry = await lab.ingest(URI_A, TEXT + " Ny regel.")
    assert retry.reused_version and retry.document_version_id != first.document_version_id
    assert len(await lab.rows(DocumentVersionRecord)) == 2
    assert len(lab.inner.calls) == 2
    assert await vectors_for(lab, first) and await vectors_for(lab, retry)


async def test_repair_materializes_inputs_and_preserves_historical_projections(projected):
    lab, index = projected
    first = await lab.ingest(URI_A)
    old_keys = set(index.vectors)
    current = await lab.ingest(URI_A, TEXT + " Ny regel.")
    for key in set(index.vectors) - old_keys:
        del index.vectors[key]
    async with lab.factory() as session:
        assert await index_missing_persisted_documents(
            session, embeddings=_cache(lab), vector_store=lab.store,
        ) == (1, 0)
        assert not session.in_transaction()
        assert await index_missing_persisted_documents(
            session, embeddings=_cache(lab), vector_store=lab.store,
        ) == (0, 1)
    assert len(lab.inner.calls) == 2
    assert await vectors_for(lab, first) and await vectors_for(lab, current)


async def test_repair_does_not_commit_or_rollback_callers_pending_writes(projected):
    lab, index = projected
    async with lab.factory() as session:
        session.add(Kund(id=3, name="Pending", slug="pending"))
        await session.flush()
        with pytest.raises(RuntimeError, match="without an active transaction"):
            await index_missing_persisted_documents(
                session, embeddings=_cache(lab), vector_store=lab.store,
            )
        assert session.in_transaction()
        assert await session.scalar(select(Kund.id).where(Kund.id == 3)) == 3
        await session.rollback()
    assert index.puts == [] and index.gets == []


async def test_partial_index_write_is_repaired_using_persisted_keys(projected):
    lab, index = projected
    first = await lab.ingest(URI_A)
    original = dict(index.vectors)
    index.failure, index.partial_failure = RuntimeError("partial write"), True
    revised = TEXT + "\n\n# Andra delen\n\nYtterligare ny text."
    with pytest.raises(RuntimeError, match="partial write"):
        await lab.ingest(URI_A, revised)
    assert len(index.vectors) > len(original)
    retry = await lab.ingest(URI_A, revised)
    assert retry.reused_version
    assert all(index.vectors[key] == value for key, value in original.items())
    assert len(await vectors_for(lab, retry)) == retry.chunks_indexed
    assert await vectors_for(lab, first)


@pytest.mark.parametrize("write", [False, True])
async def test_isolated_profile_uses_only_current_known_keys_and_releases_database(projected, write):
    from scripts.check_source_vector_index import measure

    lab, index = projected
    result = await lab.ingest(URI_A)
    report = await measure(
        lab.factory, lab.store, _cache(lab), document_id=result.document_id, write=write,
    )
    assert report["document_version_id"] == result.document_version_id
    assert report["chunks"] == result.chunks_indexed
    assert report["present_before"] is True and report["wrote_projection"] is write
    assert report["get_seconds"] >= 0
    assert len(index.puts) == (2 if write else 1)
    assert len(lab.inner.calls) == 1


def _cache(lab):
    from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider

    return GraphEmbeddingCacheProvider(lab.factory, lab.inner)
