"""OpenAI embeddings client + write-through disk/memory cache for SSR anchors."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]

_client: AsyncOpenAI | None = None
_embedder: Embedder | None = None

# (embedding_model, normalized_text) → vector. Mirrors disk; cleared in tests.
_cache: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()

# OpenAI embedding API batch limit.
_MAX_BATCH = 2048


def get_embedding_client() -> AsyncOpenAI:
    """Client bound to settings — never reads CAMEL's mirrored OPENAI_API_KEY env."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.embedding_base_url,
            timeout=settings.embedding_timeout_seconds,
        )
    return _client


def reset_embedding_client() -> None:
    global _client
    _client = None


def set_embedder(embedder: Embedder | None) -> None:
    global _embedder
    _embedder = embedder


def _cache_dir() -> Path:
    return Path(settings.embedding_cache_dir)


def _entries_dir() -> Path:
    return _cache_dir() / "entries"


def _normalize_text(text: str) -> str:
    # Must match what we send to the API (empty → space).
    return text if text.strip() else " "


def _cache_key(text: str) -> tuple[str, str]:
    return (settings.embedding_model, _normalize_text(text))


def _entry_id(model: str, text: str) -> str:
    payload = f"{model}\0{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def _entry_path(model: str, text: str) -> Path:
    return _entries_dir() / f"{_entry_id(model, text)}.json"


def drop_memory_cache() -> None:
    """Forget in-process vectors (disk untouched). Used by tests."""
    with _lock:
        _cache.clear()


def clear_embedding_cache() -> int:
    """Clear memory + delete on-disk entries. Returns number of disk files removed."""
    with _lock:
        _cache.clear()
        entries = _entries_dir()
        removed = 0
        if entries.is_dir():
            for path in entries.glob("*.json"):
                path.unlink()
                removed += 1
        return removed


def embedding_cache_size() -> int:
    with _lock:
        return len(_cache)


def cache_get(text: str) -> list[float] | None:
    key = _cache_key(text)
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            return list(hit)
    model, norm = key
    path = _entry_path(model, norm)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Corrupt embedding cache entry {path.name}: {exc}") from exc
    if raw.get("model") != model or raw.get("text") != norm:
        raise RuntimeError(
            f"Embedding cache entry {path.name} key mismatch "
            f"(expected model={model!r})"
        )
    vector = raw.get("vector")
    if not isinstance(vector, list) or not vector:
        raise RuntimeError(f"Embedding cache entry {path.name} missing vector")
    vec = [float(x) for x in vector]
    with _lock:
        _cache[key] = vec
    return list(vec)


def cache_put(text: str, vector: list[float]) -> None:
    key = _cache_key(text)
    model, norm = key
    vec = list(vector)
    entry = {
        "id": _entry_id(model, norm),
        "model": model,
        "text": norm,
        "dims": len(vec),
        "vector": vec,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    path = _entry_path(model, norm)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp path so parallel writers for the same key cannot clobber each other.
    tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    with _lock:
        _cache[key] = vec


def list_embedding_cache_entries() -> list[dict[str, Any]]:
    """Metadata for admin UI (no vectors). Disk is source of truth."""
    entries_dir = _entries_dir()
    if not entries_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(entries_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Corrupt embedding cache entry {path.name}: {exc}") from exc
        text = raw.get("text")
        model = raw.get("model")
        if not isinstance(text, str) or not isinstance(model, str):
            raise RuntimeError(f"Embedding cache entry {path.name} missing model/text")
        dims = raw.get("dims")
        if dims is None and isinstance(raw.get("vector"), list):
            dims = len(raw["vector"])
        rows.append(
            {
                "id": raw.get("id") or path.stem,
                "model": model,
                "text": text,
                "dims": int(dims) if dims is not None else 0,
                "updated_at": str(raw.get("updated_at") or ""),
            }
        )
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts via inject hook or OpenAI. Does not read/write the cache."""
    if _embedder is not None:
        return await _embedder(texts)
    if not texts:
        return []
    client = get_embedding_client()
    out: list[list[float]] = []
    for start in range(0, len(texts), _MAX_BATCH):
        chunk = texts[start : start + _MAX_BATCH]
        cleaned = [_normalize_text(t) for t in chunk]
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=cleaned,
        )
        by_index = {row.index: row.embedding for row in response.data}
        for i in range(len(cleaned)):
            vec = by_index.get(i)
            if vec is None:
                raise RuntimeError(f"embedding response missing index {i}")
            out.append(list(vec))
    return out


async def embed_texts_cached(texts: list[str]) -> list[list[float]]:
    """Embed with disk/memory cache keyed by (embedding_model, text)."""
    if not texts:
        return []
    out: list[list[float] | None] = [None] * len(texts)
    missing_indices: list[int] = []
    missing_texts: list[str] = []
    for i, text in enumerate(texts):
        hit = cache_get(text)
        if hit is not None:
            out[i] = hit
        else:
            missing_indices.append(i)
            missing_texts.append(text)
    if missing_texts:
        fresh = await embed_texts(missing_texts)
        if len(fresh) != len(missing_texts):
            raise RuntimeError(
                f"embed_texts returned {len(fresh)} vectors for {len(missing_texts)} inputs"
            )
        for idx, text, vec in zip(missing_indices, missing_texts, fresh, strict=True):
            cache_put(text, vec)
            out[idx] = vec
    if any(v is None for v in out):
        raise RuntimeError("embed_texts_cached failed to fill all vectors")
    return [v for v in out if v is not None]
