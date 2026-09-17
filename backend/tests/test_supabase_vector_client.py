from types import SimpleNamespace

import pytest
from storage3.types import VectorData, VectorMatch

from app.config import settings
from app.services.knowledge.provider import KnowledgeVectorStoreError
from app.services.knowledge.supabase_vector_client import (
    SupabaseStorageVectorClient,
    _ensure_index,
)
from app.services.knowledge.vector_store import VectorBucketRecord


class FakeIndex:
    def __init__(self) -> None:
        self.put_batches = []
        self.deleted_batches = []
        self.query_kwargs = None
        self.list_pages = []

    async def put(self, vectors):
        self.put_batches.append(vectors)

    async def query(self, query_vector, **kwargs):
        self.query_kwargs = {"query_vector": query_vector, **kwargs}
        return SimpleNamespace(
            vectors=[
                VectorMatch(
                    key="key",
                    distance=0.2,
                    metadata={
                        "document_id": "doc-1",
                        "chunk_id": "chunk-1",
                        "text": "Ett underlag",
                        "title": "Titel",
                        "customer_id": 7,
                    },
                )
            ]
        )

    async def list(self, **_kwargs):
        return self.list_pages.pop(0)

    async def delete(self, keys):
        self.deleted_batches.append(keys)


def _record(number: int = 1) -> VectorBucketRecord:
    return VectorBucketRecord(
        document_id="doc-1",
        chunk_id=f"chunk-{number}",
        text="Ett underlag",
        title="Titel",
        locator="s. 1",
        provider="supabase",
        embedding=[0.1, 0.2, 0.3],
        metadata={"customer_id": 7, "nested": {"ignored": True}},
    )


async def test_live_client_upserts_in_bounded_batches():
    index = FakeIndex()
    client = SupabaseStorageVectorClient(index)
    await client.upsert([_record(number) for number in range(501)])
    assert [len(batch) for batch in index.put_batches] == [500, 1]
    first = index.put_batches[0][0]
    assert first.data.float32 == [0.1, 0.2, 0.3]
    assert first.metadata["document_id"] == "doc-1"
    assert "nested" not in first.metadata


async def test_live_client_queries_with_scope_filters_and_normalizes_score():
    index = FakeIndex()
    client = SupabaseStorageVectorClient(index)
    records = await client.query(vector=[0.1, 0.2, 0.3], filters={"customer_id": 7}, limit=4)
    assert index.query_kwargs == {
        "query_vector": VectorData(float32=[0.1, 0.2, 0.3]),
        "topK": 4,
        "filter": {"customer_id": 7},
        "return_distance": True,
        "return_metadata": True,
    }
    assert records[0].score == pytest.approx(0.8)
    assert records[0].text == "Ett underlag"


async def test_live_client_replace_upserts_before_deleting_stale_keys():
    index = FakeIndex()
    index.list_pages = [
        SimpleNamespace(
            vectors=[
                VectorMatch(key="old-a", metadata={"document_id": "doc-1"}),
                VectorMatch(key="keep", metadata={"document_id": "doc-2"}),
            ],
            nextToken=None,
        ),
    ]
    client = SupabaseStorageVectorClient(index)
    await client.replace("doc-1", [_record(number=2)])
    assert len(index.put_batches) == 1
    assert index.deleted_batches == [["old-a"]]


async def test_live_client_deletes_every_chunk_for_document():
    index = FakeIndex()
    index.list_pages = [
        SimpleNamespace(
            vectors=[
                VectorMatch(key="a", metadata={"document_id": "doc-1"}),
                VectorMatch(key="b", metadata={"document_id": "doc-2"}),
            ],
            nextToken="next",
        ),
        SimpleNamespace(
            vectors=[VectorMatch(key="c", metadata={"document_id": "doc-1"})],
            nextToken=None,
        ),
    ]
    client = SupabaseStorageVectorClient(index)
    await client.delete("doc-1")
    assert index.deleted_batches == [["a", "c"]]


class FakeBucket:
    def __init__(self, index) -> None:
        self.response = SimpleNamespace(index=index) if index is not None else None
        self.created = []

    async def get_index(self, _name):
        return self.response

    async def create_index(self, name, **kwargs):
        self.created.append((name, kwargs))
        self.response = SimpleNamespace(
            index=SimpleNamespace(
                dimension=kwargs["dimension"],
                distance_metric=kwargs["distance_metric"],
                data_type=kwargs["data_type"],
            )
        )


async def test_ensure_index_creates_expected_supabase_index():
    bucket = FakeBucket(None)
    await _ensure_index(bucket, settings)
    assert bucket.created == [
        (
            settings.supabase_vector_index,
            {
                "dimension": settings.embedding_dimension,
                "distance_metric": settings.supabase_vector_distance_metric,
                "data_type": "float32",
            },
        )
    ]


async def test_ensure_index_rejects_dimension_mismatch():
    bucket = FakeBucket(
        SimpleNamespace(
            dimension=settings.embedding_dimension - 1,
            distance_metric=settings.supabase_vector_distance_metric,
            data_type="float32",
        )
    )
    with pytest.raises(KnowledgeVectorStoreError, match="dimension"):
        await _ensure_index(bucket, settings)
