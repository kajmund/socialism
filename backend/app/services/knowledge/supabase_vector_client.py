"""Live Supabase Storage Vector Bucket transport for research knowledge."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from storage3 import AsyncStorageClient
from storage3.types import VectorData, VectorObject

from app.config import Settings
from app.services.knowledge.provider import KnowledgeVectorStoreError
from app.services.knowledge.vector_store import VectorBucketClient, VectorBucketRecord

_BATCH_SIZE = 500
_LIST_PAGE_SIZE = 100


@dataclass(frozen=True)
class SupabaseVectorHealth:
    status: str
    bucket: str
    index: str
    dimension: int


class SupabaseStorageVectorClient(VectorBucketClient):
    def __init__(self, index: Any) -> None:
        self._index = index

    async def upsert(self, records: Sequence[VectorBucketRecord]) -> None:
        vectors = [_vector_object(record) for record in records]
        for offset in range(0, len(vectors), _BATCH_SIZE):
            await self._index.put(vectors[offset : offset + _BATCH_SIZE])

    async def replace(
        self,
        document_id: str,
        records: Sequence[VectorBucketRecord],
    ) -> None:
        records_list = list(records)
        await self.upsert(records_list)
        new_keys = {_record_key(record) for record in records_list}
        stale_keys = [
            key
            for key in await self._list_keys_for_document(document_id)
            if key not in new_keys
        ]
        for offset in range(0, len(stale_keys), _BATCH_SIZE):
            await self._index.delete(stale_keys[offset : offset + _BATCH_SIZE])

    async def query(
        self,
        *,
        vector: Sequence[float],
        filters: Mapping[str, Any],
        limit: int,
    ) -> Sequence[VectorBucketRecord]:
        response = await self._index.query(
            VectorData(float32=list(vector)),
            topK=limit,
            filter=_vector_filter(filters),
            return_distance=True,
            return_metadata=True,
        )
        return [_record_from_match(match) for match in response.vectors]

    async def delete(self, document_id: str) -> None:
        keys = await self._list_keys_for_document(document_id)
        for offset in range(0, len(keys), _BATCH_SIZE):
            await self._index.delete(keys[offset : offset + _BATCH_SIZE])

    async def _list_keys_for_document(self, document_id: str) -> list[str]:
        keys: list[str] = []
        next_token: str | None = None
        while True:
            page = await self._index.list(
                max_results=_LIST_PAGE_SIZE,
                next_token=next_token,
                return_data=False,
                return_metadata=True,
            )
            keys.extend(
                match.key
                for match in page.vectors
                if (match.metadata or {}).get("document_id") == document_id
            )
            next_token = page.nextToken
            if not next_token:
                break
        return keys


def _vector_filter(filters: Mapping[str, Any]) -> dict[str, Any] | None:
    conditions = [{key: value} for key, value in filters.items()]
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


@dataclass
class SupabaseVectorRuntime:
    storage: AsyncStorageClient
    client: SupabaseStorageVectorClient
    health: SupabaseVectorHealth

    async def close(self) -> None:
        await self.storage.session.aclose()


async def start_supabase_vector_runtime(settings: Settings) -> SupabaseVectorRuntime:
    storage = AsyncStorageClient(
        f"{settings.supabase_vector_url.rstrip('/')}/storage/v1",
        headers={
            "Authorization": f"Bearer {settings.supabase_vector_service_role_key}",
            "apikey": settings.supabase_vector_service_role_key,
        },
    )
    try:
        bucket = storage.vectors().from_(settings.supabase_vector_bucket)
        await _ensure_bucket(storage, settings.supabase_vector_bucket)
        await _ensure_index(bucket, settings)
        index = bucket.index(settings.supabase_vector_index)
        return SupabaseVectorRuntime(
            storage=storage,
            client=SupabaseStorageVectorClient(index),
            health=SupabaseVectorHealth(
                status="ok",
                bucket=settings.supabase_vector_bucket,
                index=settings.supabase_vector_index,
                dimension=settings.embedding_dimension,
            ),
        )
    except Exception:
        await storage.session.aclose()
        raise


async def _ensure_bucket(storage: AsyncStorageClient, bucket_name: str) -> None:
    vectors = storage.vectors()
    if await vectors.get_bucket(bucket_name) is None:
        await vectors.create_bucket(bucket_name)


async def _ensure_index(bucket: Any, settings: Settings) -> None:
    response = await bucket.get_index(settings.supabase_vector_index)
    if response is None:
        await bucket.create_index(
            settings.supabase_vector_index,
            dimension=settings.embedding_dimension,
            distance_metric=settings.supabase_vector_distance_metric,
            data_type="float32",
        )
        response = await bucket.get_index(settings.supabase_vector_index)
    if response is None:
        raise KnowledgeVectorStoreError(
            f"Supabase vector index {settings.supabase_vector_index!r} was not created"
        )
    index = response.index
    if index.dimension != settings.embedding_dimension:
        raise KnowledgeVectorStoreError(
            f"Supabase vector index dimension {index.dimension} does not match "
            f"EMBEDDING_DIMENSION={settings.embedding_dimension}"
        )
    if index.distance_metric != settings.supabase_vector_distance_metric:
        raise KnowledgeVectorStoreError(
            f"Supabase vector index distance metric {index.distance_metric!r} does not match "
            f"SUPABASE_VECTOR_DISTANCE_METRIC={settings.supabase_vector_distance_metric!r}"
        )
    if index.data_type != "float32":
        raise KnowledgeVectorStoreError(
            f"Supabase vector index data type {index.data_type!r} is not 'float32'"
        )


def _vector_object(record: VectorBucketRecord) -> VectorObject:
    return VectorObject(
        key=_record_key(record),
        data=VectorData(float32=record.embedding),
        metadata=_record_metadata(record),
    )


def _record_key(record: VectorBucketRecord) -> str:
    identity = f"{record.document_id}\0{record.chunk_id}".encode()
    return hashlib.sha256(identity).hexdigest()


def _record_metadata(record: VectorBucketRecord) -> dict[str, str | bool | float]:
    metadata: dict[str, str | bool | float] = {
        key: value
        for key, value in record.metadata.items()
        if isinstance(value, (str, bool, float, int)) and value is not None
    }
    metadata.update(
        {
            "document_id": record.document_id,
            "chunk_id": record.chunk_id,
            "text": record.text,
            "title": record.title,
        }
    )
    for key, value in (
        ("locator", record.locator),
        ("provider", record.provider),
        ("version", record.version),
        ("external_id", record.external_id),
    ):
        if value is not None:
            metadata[key] = value
    return metadata


def _record_from_match(match: Any) -> VectorBucketRecord:
    metadata = dict(match.metadata or {})
    distance = match.distance
    return VectorBucketRecord(
        document_id=str(metadata["document_id"]),
        chunk_id=str(metadata["chunk_id"]),
        text=str(metadata["text"]),
        title=str(metadata["title"]),
        score=None if distance is None else 1.0 - float(distance),
        locator=_string_or_none(metadata.get("locator")),
        provider=_string_or_none(metadata.get("provider")),
        version=_string_or_none(metadata.get("version")),
        external_id=_string_or_none(metadata.get("external_id")),
        metadata=metadata,
    )


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
