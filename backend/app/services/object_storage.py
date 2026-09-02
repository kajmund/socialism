"""Supabase Storage via the S3-compatible API.

boto3 is here because AWS SigV4 + the S3 protocol are not something we write
correctly in a few dozen lines. One path: this client. Tests inject MemoryObjectStorage.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings

KIND_ANNUAL_REPORT = "annual_report"
KIND_REPORT_HTML = "report_html"
KIND_REPORT_SLOTS = "report_slots"
KIND_REPORT_JSON = "report_json"

MAX_ANNUAL_REPORT_BYTES = 25 * 1024 * 1024

_TOKEN = re.compile(r"[^a-z0-9-]+")
_FILENAME_SAFE = re.compile(r"[^\w.\-]+", re.UNICODE)

_ANNUAL_REPORT_TYPES = {
    "application/pdf": (".pdf",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}


class ObjectStorageError(Exception):
    """S3/Storage operation failed."""


class MemoryObjectStorage:
    """In-process store for tests — same methods as S3ObjectStorage."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, tuple[bytes, str]]] = {}

    def ensure_bucket(self, name: str) -> None:
        self.buckets.setdefault(name, {})

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.ensure_bucket(bucket)
        self.buckets[bucket][key] = (data, content_type)

    def get_object(self, bucket: str, key: str) -> tuple[bytes, str]:
        try:
            return self.buckets[bucket][key]
        except KeyError as exc:
            raise ObjectStorageError(f"Object not found: {bucket}/{key}") from exc

    def delete_object(self, bucket: str, key: str) -> None:
        bucket_objects = self.buckets.get(bucket)
        if bucket_objects is not None:
            bucket_objects.pop(key, None)


class S3ObjectStorage:
    def _client(self):
        key_id = settings.supabase_s3_access_key_id.strip()
        secret = settings.supabase_s3_secret_access_key.strip()
        region = settings.supabase_s3_region.strip()
        if not key_id or not secret or not region:
            raise ObjectStorageError(
                "SUPABASE_S3_ACCESS_KEY_ID, SUPABASE_S3_SECRET_ACCESS_KEY, and "
                "SUPABASE_S3_REGION are required — create S3 access keys in "
                "Supabase Dashboard → Storage → S3"
            )
        return boto3.client(
            "s3",
            endpoint_url=supabase_s3_endpoint(settings.supabase_url),
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name=region,
            config=Config(s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self, name: str) -> None:
        client = self._client()
        try:
            client.head_bucket(Bucket=name)
            return
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "404 Not Found", "NotFound"}:
                raise ObjectStorageError(f"head_bucket {name}: {exc}") from exc
        try:
            client.create_bucket(Bucket=name)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                return
            raise ObjectStorageError(f"create_bucket {name}: {exc}") from exc

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client().put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as exc:
            raise ObjectStorageError(f"put_object {bucket}/{key}: {exc}") from exc

    def get_object(self, bucket: str, key: str) -> tuple[bytes, str]:
        try:
            response = self._client().get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            raise ObjectStorageError(f"get_object {bucket}/{key}: {exc}") from exc
        body = response["Body"].read()
        content_type = str(response.get("ContentType") or "application/octet-stream")
        return body, content_type

    def delete_object(self, bucket: str, key: str) -> None:
        try:
            self._client().delete_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            raise ObjectStorageError(f"delete_object {bucket}/{key}: {exc}") from exc


_storage: MemoryObjectStorage | S3ObjectStorage | None = None


def set_object_storage(storage: MemoryObjectStorage | S3ObjectStorage | None) -> None:
    global _storage
    _storage = storage


def get_object_storage() -> MemoryObjectStorage | S3ObjectStorage:
    global _storage
    if _storage is None:
        _storage = S3ObjectStorage()
    return _storage


def supabase_s3_endpoint(supabase_url: str) -> str:
    host = urlparse(supabase_url).hostname or ""
    ref = host.split(".")[0]
    if not ref:
        raise ValueError("SUPABASE_URL has no project ref")
    return f"https://{ref}.storage.supabase.co/storage/v1/s3"


def bucket_name(kund_slug: str) -> str:
    slug = _token(kund_slug)
    if not slug:
        raise ValueError("kund slug is required for bucket name")
    name = slug[:63].strip("-")
    if len(name) < 3:
        raise ValueError(f"bucket name too short: {name!r}")
    return name


def module_prefix(module: str) -> str:
    """First path segment under the kund bucket."""
    mod = _token(module)
    if not mod:
        raise ValueError("module is required for object key")
    return mod


def _token(raw: str) -> str:
    cleaned = _TOKEN.sub("-", raw.strip().lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def safe_filename(name: str) -> str:
    base = Path(name).name.strip()
    cleaned = _FILENAME_SAFE.sub("_", base).strip("._")
    return cleaned[:200] or "file"


def validate_annual_report(filename: str, content_type: str, data: bytes) -> str:
    if not data:
        raise ValueError("empty file")
    if len(data) > MAX_ANNUAL_REPORT_BYTES:
        mb = MAX_ANNUAL_REPORT_BYTES // (1024 * 1024)
        raise ValueError(f"file exceeds {mb} MB limit")
    ctype = (content_type or "").split(";")[0].strip().lower()
    lower_name = filename.lower()
    if ctype == "application/octet-stream" or not ctype:
        ctype = _type_from_name(lower_name)
    if ctype == "application/pdf" or lower_name.endswith(".pdf"):
        if not data.startswith(b"%PDF"):
            raise ValueError("file is not a PDF")
        return "application/pdf"
    if ctype in _ANNUAL_REPORT_TYPES:
        return ctype
    raise ValueError("only PDF and images (JPEG, PNG, WebP) are allowed")


def _type_from_name(filename: str) -> str:
    for mime, suffixes in _ANNUAL_REPORT_TYPES.items():
        if filename.endswith(suffixes):
            return mime
    return ""


async def ensure_bucket(name: str) -> None:
    storage = get_object_storage()
    await asyncio.to_thread(storage.ensure_bucket, name)


async def put_object(bucket: str, key: str, data: bytes, content_type: str) -> None:
    storage = get_object_storage()
    await asyncio.to_thread(storage.put_object, bucket, key, data, content_type)


async def get_object(bucket: str, key: str) -> tuple[bytes, str]:
    storage = get_object_storage()
    return await asyncio.to_thread(storage.get_object, bucket, key)


async def delete_object(bucket: str, key: str) -> None:
    storage = get_object_storage()
    await asyncio.to_thread(storage.delete_object, bucket, key)
