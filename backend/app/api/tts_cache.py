"""Admin endpoints for the disk-based ElevenLabs TTS cache."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.config import settings
from app.services.tts_cache import (
    clear_tts_cache,
    list_tts_cache_entries,
    tts_cache_stats,
)

router = APIRouter(
    prefix="/tts",
    tags=["tts"],
    dependencies=[Depends(require_admin)],
)


class TtsCacheEntryOut(BaseModel):
    digest: str
    size_bytes: int
    modified_at: str


class TtsCacheListOut(BaseModel):
    cache_dir: str
    count: int
    size_bytes: int
    max_bytes: int
    entries: list[TtsCacheEntryOut]


class TtsCacheClearOut(BaseModel):
    cleared: int


@router.get("/cache", response_model=TtsCacheListOut)
async def get_tts_cache() -> TtsCacheListOut:
    stats = tts_cache_stats(settings.tts_cache_dir, max_bytes=settings.tts_cache_max_bytes)
    entries = [
        TtsCacheEntryOut(
            digest=str(row["digest"]),
            size_bytes=int(row["size_bytes"]),
            modified_at=str(row["modified_at"]),
        )
        for row in list_tts_cache_entries(settings.tts_cache_dir)
    ]
    return TtsCacheListOut(
        cache_dir=settings.tts_cache_dir,
        count=stats["entries"],
        size_bytes=stats["size_bytes"],
        max_bytes=stats["max_bytes"],
        entries=entries,
    )


@router.delete("/cache", response_model=TtsCacheClearOut)
async def delete_tts_cache() -> TtsCacheClearOut:
    return TtsCacheClearOut(cleared=clear_tts_cache(settings.tts_cache_dir))
