"""Budskap image upload + SHA256 caption cache."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.image_cache import (
    clear_image_cache,
    compose_feed_body,
    delete_entry,
    ensure_cached_image,
    get_entry,
    image_bytes_path,
    list_entries,
    update_caption,
)
from app.services.playground_image import MAX_IMAGE_BYTES

router = APIRouter(prefix="/images", tags=["messages"])

Locale = Literal["sv", "en"]


class ImageCacheEntryOut(BaseModel):
    sha256: str
    caption: str
    content_type: str
    size_bytes: int
    vision_provider: str
    vision_model: str
    caption_edited: bool
    created_at: str
    updated_at: str


class ImageUploadOut(BaseModel):
    entry: ImageCacheEntryOut
    cache_hit: bool


class ImageCacheListOut(BaseModel):
    cache_dir: str
    count: int
    entries: list[ImageCacheEntryOut]


class CaptionUpdate(BaseModel):
    caption: str = Field(min_length=1)


class CacheDeleteOut(BaseModel):
    deleted: bool


class CacheClearOut(BaseModel):
    cleared: int


def _serialize(row: dict) -> ImageCacheEntryOut:
    return ImageCacheEntryOut(
        sha256=str(row["sha256"]),
        caption=str(row["caption"]),
        content_type=str(row["content_type"]),
        size_bytes=int(row["size_bytes"]),
        vision_provider=str(row["vision_provider"]),
        vision_model=str(row["vision_model"]),
        caption_edited=bool(row.get("caption_edited")),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


@router.post("/upload", response_model=ImageUploadOut)
async def upload_image(
    image: UploadFile = File(...),
    locale: Locale = Form(default="sv"),
    vision_provider: str | None = Form(default=None),
    vision_model: str | None = Form(default=None),
) -> ImageUploadOut:
    # Cap read before buffering — validate_image runs after read; unbounded read()
    # would allow multi‑GB uploads to exhaust worker memory.
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        mb = MAX_IMAGE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Image exceeds {mb} MB limit")
    try:
        entry, cache_hit = await ensure_cached_image(
            raw,
            content_type=image.content_type or "application/octet-stream",
            locale=locale,
            vision_provider=vision_provider,
            vision_model=vision_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ImageUploadOut(entry=_serialize(entry), cache_hit=cache_hit)


@router.get("/cache", response_model=ImageCacheListOut)
async def get_image_cache() -> ImageCacheListOut:
    from app.config import settings

    entries = [_serialize(row) for row in list_entries()]
    return ImageCacheListOut(
        cache_dir=settings.image_cache_dir,
        count=len(entries),
        entries=entries,
    )


@router.get("/cache/{sha256}", response_model=ImageCacheEntryOut)
async def get_image_cache_entry(sha256: str) -> ImageCacheEntryOut:
    entry = get_entry(sha256)
    if entry is None:
        raise HTTPException(status_code=404, detail="Image cache entry not found")
    return _serialize(entry)


@router.patch("/cache/{sha256}", response_model=ImageCacheEntryOut)
async def patch_image_caption(sha256: str, body: CaptionUpdate) -> ImageCacheEntryOut:
    try:
        entry = update_caption(sha256, body.caption)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(entry)


@router.delete("/cache/{sha256}", response_model=CacheDeleteOut)
async def delete_image_cache_entry(sha256: str) -> CacheDeleteOut:
    return CacheDeleteOut(deleted=delete_entry(sha256))


@router.delete("/cache", response_model=CacheClearOut)
async def delete_all_image_cache() -> CacheClearOut:
    return CacheClearOut(cleared=clear_image_cache())


@router.get("/cache/{sha256}/file")
async def get_cached_image_file(sha256: str) -> FileResponse:
    entry = get_entry(sha256)
    if entry is None:
        raise HTTPException(status_code=404, detail="Image cache entry not found")
    path = image_bytes_path(sha256)
    if path is None:
        raise HTTPException(status_code=404, detail="Image bytes not found")
    return FileResponse(
        path,
        media_type=str(entry["content_type"]),
        filename=f"{sha256[:16]}.bin",
    )


def message_image_sha256(metadata: dict | None) -> str | None:
    if not metadata:
        return None
    raw = metadata.get("image_sha256")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return None


def resolve_message_feed_body(*, body: str, metadata: dict | None) -> str:
    digest = message_image_sha256(metadata)
    if not digest:
        return body.strip()
    entry = get_entry(digest)
    if entry is None:
        raise ValueError(f"Image cache entry {digest!r} not found for message")
    return compose_feed_body(body=body, caption=str(entry.get("caption") or ""))
