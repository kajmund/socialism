"""Admin endpoints for the SSR embedding cache."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.services.ssr.embeddings import (
    clear_embedding_cache,
    list_embedding_cache_entries,
)

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


class CacheEntryOut(BaseModel):
    id: str
    model: str
    text: str
    dims: int
    updated_at: str


class CacheListOut(BaseModel):
    embedding_model: str
    cache_dir: str
    count: int
    entries: list[CacheEntryOut]


class CacheClearOut(BaseModel):
    cleared: int


@router.get("/cache", response_model=CacheListOut)
async def get_embedding_cache() -> CacheListOut:
    entries = [
        CacheEntryOut(
            id=str(row["id"]),
            model=str(row["model"]),
            text=str(row["text"]),
            dims=int(row["dims"]),
            updated_at=str(row["updated_at"]),
        )
        for row in list_embedding_cache_entries()
    ]
    return CacheListOut(
        embedding_model=settings.embedding_model,
        cache_dir=settings.embedding_cache_dir,
        count=len(entries),
        entries=entries,
    )


@router.delete("/cache", response_model=CacheClearOut)
async def delete_embedding_cache() -> CacheClearOut:
    cleared = clear_embedding_cache()
    return CacheClearOut(cleared=cleared)
