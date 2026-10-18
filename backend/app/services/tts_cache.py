"""Disk cache for streamed ElevenLabs live-speech audio segments.

SpeechSegmenter already normalizes streamed reply text into short phrases
(roughly 110-220 characters); those phrases are the cache unit. An entry holds
the provider's PCM bytes for one (voice, model, output format, language,
phrase) combination, so an identical phrase costs no provider call at all.
This cache is pure disk I/O - it never touches the database.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

_CHUNK_BYTES = 64 * 1024
_STALE_PART_SECONDS = 3600
_KEY_SEPARATOR = "\x00"


class TtsStreamer(Protocol):
    async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]: ...


def tts_key_namespace(*, model_id: str, voice_id: str, output_format: str) -> str:
    """Bind cache entries to one provider configuration so settings changes miss cleanly."""
    return f"{model_id}|{voice_id}|{output_format}"


def cache_digest(namespace: str, language: str, text: str) -> str:
    raw = f"{namespace}{_KEY_SEPARATOR}{language}{_KEY_SEPARATOR}{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sweep_stale_parts(cache_dir: Path) -> None:
    """Drop abandoned .part files left by crashed or cancelled syntheses."""
    if not cache_dir.is_dir():
        return
    cutoff = time.time() - _STALE_PART_SECONDS
    for path in cache_dir.glob("*.part"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue


def _pcm_entries(cache_dir: Path) -> list[tuple[Path, int, float]]:
    if not cache_dir.is_dir():
        return []
    entries: list[tuple[Path, int, float]] = []
    for path in cache_dir.glob("*.pcm"):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        entries.append((path, stat.st_size, stat.st_mtime))
    return entries


def tts_cache_stats(cache_dir: str | Path, *, max_bytes: int) -> dict[str, int]:
    root = Path(cache_dir)
    _sweep_stale_parts(root)
    entries = _pcm_entries(root)
    return {
        "entries": len(entries),
        "size_bytes": sum(size for _path, size, _mtime in entries),
        "max_bytes": max_bytes,
    }


def list_tts_cache_entries(cache_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(cache_dir)
    rows: list[dict[str, Any]] = []
    for path, size, mtime in sorted(_pcm_entries(root), key=lambda row: row[2], reverse=True):
        rows.append(
            {
                "digest": path.stem,
                "size_bytes": size,
                "modified_at": datetime.fromtimestamp(mtime, UTC).isoformat(),
            }
        )
    return rows


def clear_tts_cache(cache_dir: str | Path) -> int:
    root = Path(cache_dir)
    count = len(_pcm_entries(root))
    if root.is_dir():
        shutil.rmtree(root)
    return count


class CachedTts:
    """Streaming TTS with a disk cache; misses tee the stream into a .pcm entry."""

    def __init__(
        self,
        provider: TtsStreamer,
        *,
        cache_dir: str | Path,
        max_bytes: int,
        key_namespace: str,
    ) -> None:
        self._provider = provider
        self._dir = Path(cache_dir)
        self._max_bytes = max_bytes
        self._namespace = key_namespace
        self._inflight: dict[str, asyncio.Event] = {}
        _sweep_stale_parts(self._dir)

    def _pcm_path(self, digest: str) -> Path:
        return self._dir / f"{digest}.pcm"

    def stats(self) -> dict[str, int]:
        return tts_cache_stats(self._dir, max_bytes=self._max_bytes)

    def clear(self) -> int:
        return clear_tts_cache(self._dir)

    async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
        """Yield PCM for `text`, from disk on a hit or from one shared synthesis on a miss."""
        digest = cache_digest(self._namespace, language, text)
        while True:
            data = self._read_hit(digest)
            if data is not None:
                for offset in range(0, len(data), _CHUNK_BYTES):
                    yield data[offset : offset + _CHUNK_BYTES]
                return
            event = self._inflight.get(digest)
            if event is not None:
                await event.wait()
                continue
            event = asyncio.Event()
            self._inflight[digest] = event
            try:
                async for chunk in self._synthesize(digest, text, language):
                    yield chunk
            finally:
                self._inflight.pop(digest, None)
                event.set()
            return

    def _read_hit(self, digest: str) -> bytes | None:
        path = self._pcm_path(digest)
        return path.read_bytes() if path.is_file() else None

    async def _synthesize(self, digest: str, text: str, language: str) -> AsyncIterator[bytes]:
        self._dir.mkdir(parents=True, exist_ok=True)
        temp = self._dir / f"{digest}.{uuid4().hex}.part"
        try:
            with temp.open("wb") as handle:
                async for chunk in self._provider.stream(text, language=language):
                    if chunk:
                        handle.write(chunk)
                        yield chunk
            try:
                os.replace(temp, self._pcm_path(digest))
            except FileNotFoundError:
                # Admin cleared the cache mid-synthesis; audio already streamed.
                pass
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        self._evict_over_capacity()

    def _evict_over_capacity(self) -> None:
        entries = _pcm_entries(self._dir)
        total = sum(size for _path, size, _mtime in entries)
        if total <= self._max_bytes:
            return
        for path, size, _mtime in sorted(entries, key=lambda row: row[2]):
            if total <= self._max_bytes:
                return
            path.unlink(missing_ok=True)
            total -= size


def cached_tts(
    provider_factory: Callable[..., TtsStreamer],
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    cache_dir: str | Path,
    max_bytes: int,
) -> CachedTts:
    """Build a provider plus its disk cache, namespaced to that configuration.

    The factory stays injectable so tests can monkeypatch the provider class
    at the caller's module boundary.
    """
    provider = provider_factory(
        api_key=api_key,
        voice_id=voice_id,
        model_id=model_id,
        output_format=output_format,
    )
    return CachedTts(
        provider,
        cache_dir=cache_dir,
        max_bytes=max_bytes,
        key_namespace=tts_key_namespace(
            model_id=model_id,
            voice_id=voice_id,
            output_format=output_format,
        ),
    )
