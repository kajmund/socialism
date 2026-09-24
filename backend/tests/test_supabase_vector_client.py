from types import SimpleNamespace

import pytest
from storage3.types import VectorData, VectorMatch

from app.config import settings
from app.services.knowledge import supabase_vector_client as module
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
        self.events = []
        self.query_kwargs = None
        self.get_kwargs = None
        self.list_pages = []
        self.get_vectors = []

    async def put(self, vectors):
        self.put_batches.append(vectors)
        self.events.append(("put", [vector.key for vector in vectors]))

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

    async def get(self, *keys, **kwargs):
        self.get_kwargs = {"keys": keys, **kwargs}
        return SimpleNamespace(vectors=list(self.get_vectors))

    async def list(self, **_kwargs):
        return self.list_pages.pop(0)

    async def delete(self, keys):
        self.deleted_batches.append(keys)
        self.events.append(("delete", list(keys)))


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


async def test_live_client_gets_vectors_by_document_and_chunk_id():
    index = FakeIndex()
    index.get_vectors = [
        VectorMatch(
            key="ignored",
            data=VectorData(float32=[0.4, 0.5, 0.6]),
            metadata={
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "text": "Ett underlag",
                "title": "Titel",
                "document_version_id": "ver-1",
            },
        )
    ]
    client = SupabaseStorageVectorClient(index)
    records = await client.get(document_id="doc-1", chunk_ids=["chunk-1"])
    assert index.get_kwargs is not None
    assert index.get_kwargs["return_data"] is True
    assert index.get_kwargs["return_metadata"] is True
    assert records[0].embedding == [0.4, 0.5, 0.6]
    assert records[0].chunk_id == "chunk-1"
    assert records[0].metadata["document_version_id"] == "ver-1"


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
    assert [event for event, _keys in index.events] == ["put", "delete"]


async def test_live_client_combines_multiple_filters_with_explicit_and():
    index = FakeIndex()
    client = SupabaseStorageVectorClient(index)

    await client.query(
        vector=[0.1, 0.2, 0.3],
        filters={
            "customer_id": 7,
            "case_id": "document-1",
            "module": "expertgranskning",
            "knowledge_kind": "document_item",
        },
        limit=4,
    )

    assert index.query_kwargs["filter"] == {
        "$and": [
            {"customer_id": 7},
            {"case_id": "document-1"},
            {"module": "expertgranskning"},
            {"knowledge_kind": "document_item"},
        ]
    }


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


async def test_vector_runtime_uses_product_project_credentials(monkeypatch):
    captured = {}
    index = object()

    class RuntimeBucket:
        def index(self, name):
            captured["index_name"] = name
            return index

    class RuntimeVectors:
        def from_(self, name):
            captured["bucket_name"] = name
            return RuntimeBucket()

    class RuntimeStorage:
        session = SimpleNamespace(aclose=None)

        def __init__(self, url, *, headers):
            captured["url"] = url
            captured["headers"] = headers

        def vectors(self):
            return RuntimeVectors()

    async def noop(*_args):
        return None

    monkeypatch.setattr(module, "AsyncStorageClient", RuntimeStorage)
    monkeypatch.setattr(module, "_ensure_bucket", noop)
    monkeypatch.setattr(module, "_ensure_index", noop)
    runtime_settings = SimpleNamespace(
        supabase_url="https://product.supabase.co/",
        supabase_service_role_key="product-secret",
        supabase_vector_bucket="research-knowledge",
        supabase_vector_index="documents-openai",
        embedding_dimension=3072,
    )

    runtime = await module.start_supabase_vector_runtime(runtime_settings)

    assert captured == {
        "url": "https://product.supabase.co/storage/v1",
        "headers": {
            "Authorization": "Bearer product-secret",
            "apikey": "product-secret",
        },
        "bucket_name": "research-knowledge",
        "index_name": "documents-openai",
    }
    assert runtime.client._index is index
