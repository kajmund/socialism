"""Delete only an empty standard bucket identified by this run's exact inventory."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Collection

from botocore.exceptions import ClientError
from storage3 import AsyncStorageClient
from storage3.exceptions import StorageApiError

from app.services.object_storage import S3ObjectStorage

_SCHEMA = re.compile(r"workspace_live_[0-9a-f]{12}\Z")


class WorkspaceBucketCleanupError(RuntimeError):
    """Identity, object absence or bucket emptiness could not be verified."""


async def remove_empty_standard_bucket(
    *,
    schema: str,
    storage_inventory: Collection[tuple[str, str]],
    storage: AsyncStorageClient,
) -> dict:
    bucket, keys = _captured_bucket(schema, storage_inventory)
    try:
        actual = await storage.get_bucket(bucket)
    except StorageApiError as exc:
        if str(exc.status) != "404":
            raise
        return {"bucket": bucket, "status": "already_absent", "verified_absent": True}
    if actual.id != bucket or actual.name != bucket:
        raise WorkspaceBucketCleanupError("Storage bucket identity does not match the fixture")
    proof = await asyncio.to_thread(_verify_empty_bucket, bucket, keys)
    await storage.delete_bucket(bucket)
    try:
        await storage.get_bucket(bucket)
    except StorageApiError as exc:
        if str(exc.status) != "404":
            raise
        return {"bucket": bucket, "status": "deleted", "verified_absent": True, **proof}
    raise WorkspaceBucketCleanupError("Deleted fixture bucket is still present")


def _captured_bucket(schema: str, inventory: Collection[tuple[str, str]]) -> tuple[str, list[str]]:
    if not _SCHEMA.fullmatch(schema) or not inventory:
        raise WorkspaceBucketCleanupError(
            "Exact fixture schema and captured storage inventory required"
        )
    expected = schema.replace("_", "-")
    if any(bucket != expected or not isinstance(key, str) or not key for bucket, key in inventory):
        raise WorkspaceBucketCleanupError("Captured storage inventory crossed the fixture bucket")
    return expected, sorted({key for _bucket, key in inventory})


def _verify_empty_bucket(bucket: str, keys: list[str]) -> dict:
    client = S3ObjectStorage()._client()
    for key in keys:
        try:
            client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise WorkspaceBucketCleanupError(
                    "Captured fixture object absence is unverified"
                ) from exc
        else:
            raise WorkspaceBucketCleanupError("Captured fixture object is still present")
    listing = client.list_objects_v2(Bucket=bucket, MaxKeys=1)
    if listing.get("Contents") or listing.get("IsTruncated") or listing.get("KeyCount", 0) != 0:
        raise WorkspaceBucketCleanupError("Fixture bucket is not empty")
    return {"captured_object_heads_404": len(keys), "listed_keys": 0, "empty_before_delete": True}
