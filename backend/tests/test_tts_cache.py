"""Tests for the disk-based ElevenLabs TTS phrase cache (no network)."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import AsyncIterator

import pytest

from app.config import settings
from app.services.tts_cache import (
    CachedTts,
    cache_digest,
    cached_tts,
    clear_tts_cache,
    list_tts_cache_entries,
    tts_cache_stats,
    tts_key_namespace,
)
from tests.conftest import USER_USER_ID, mint_access_token

NAMESPACE = tts_key_namespace(
    model_id="eleven_v4_turbo",
    voice_id="voice",
    output_format="pcm_24000",
)


class FakeTts:
    def __init__(self, chunks: list[bytes] | None = None, **_kwargs: object) -> None:
        self.chunks = chunks or []
        self.calls = 0

    async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
        self.calls += 1
        for chunk in self.chunks:
            yield chunk


def _cache(tmp_path, provider, *, max_bytes: int = 1_000_000) -> CachedTts:
    return CachedTts(
        provider,
        cache_dir=tmp_path / "cache",
        max_bytes=max_bytes,
        key_namespace=NAMESPACE,
    )


async def _collect(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


async def test_miss_streams_provider_and_hit_reuses_disk(tmp_path) -> None:
    provider = FakeTts([b"abc", b"def"])
    cache = _cache(tmp_path, provider)
    first = await _collect(cache.stream("Hej.", language="sv"))
    second = await _collect(cache.stream("Hej.", language="sv"))
    assert first == second == b"abcdef"
    assert provider.calls == 1
    assert len(list((tmp_path / "cache").glob("*.pcm"))) == 1
    assert not list((tmp_path / "cache").glob("*.part"))


async def test_hit_reads_file_in_64k_chunks(tmp_path) -> None:
    payload = b"x" * 100_000
    cache = _cache(tmp_path, FakeTts([payload]))
    assert await _collect(cache.stream("Lång fras.", language="sv")) == payload
    chunks = [chunk async for chunk in cache.stream("Lång fras.", language="sv")]
    assert [len(chunk) for chunk in chunks] == [64 * 1024, 100_000 - 64 * 1024]


async def test_key_isolation_by_namespace_language_and_text(tmp_path) -> None:
    cache = _cache(tmp_path, FakeTts([b"x"]))
    await _collect(cache.stream("Hej.", language="sv"))
    await _collect(cache.stream("Hej.", language="en"))
    await _collect(cache.stream("Hej igen.", language="sv"))
    other_voice = CachedTts(
        FakeTts([b"y"]),
        cache_dir=tmp_path / "cache",
        max_bytes=1_000_000,
        key_namespace=tts_key_namespace(model_id="m", voice_id="other", output_format="f"),
    )
    await _collect(other_voice.stream("Hej.", language="sv"))
    assert len(list((tmp_path / "cache").glob("*.pcm"))) == 4


def test_digest_matches_documented_key_format() -> None:
    expected = hashlib.sha256(f"{NAMESPACE}\x00sv\x00Hej.".encode("utf-8")).hexdigest()
    assert cache_digest(NAMESPACE, "sv", "Hej.") == expected
    assert cache_digest(NAMESPACE, "sv", "Hej.") != cache_digest(NAMESPACE, "en", "Hej.")


async def test_cancelled_miss_is_not_cached_and_temp_is_removed(tmp_path) -> None:
    started = asyncio.Event()

    class Hanging(FakeTts):
        async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
            self.calls += 1
            yield b"abc"
            started.set()
            await asyncio.Event().wait()
            yield b"def"

    cache = _cache(tmp_path, Hanging([]))
    task = asyncio.create_task(_collect(cache.stream("Hej.", language="sv")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list((tmp_path / "cache").iterdir()) == []


async def test_provider_error_propagates_and_is_not_cached(tmp_path) -> None:
    class Boom(FakeTts):
        async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
            self.calls += 1
            yield b"abc"
            raise RuntimeError("synthesis failed")

    provider = Boom([])
    cache = _cache(tmp_path, provider)
    with pytest.raises(RuntimeError, match="synthesis failed"):
        await _collect(cache.stream("Hej.", language="sv"))
    assert list((tmp_path / "cache").iterdir()) == []
    with pytest.raises(RuntimeError, match="synthesis failed"):
        await _collect(cache.stream("Hej.", language="sv"))
    assert provider.calls == 2


async def test_empty_provider_chunks_are_skipped_in_stored_file(tmp_path) -> None:
    cache = _cache(tmp_path, FakeTts([b"", b"ab", b"", b"cd"]))
    assert await _collect(cache.stream("Hej.", language="sv")) == b"abcd"
    (path,) = (tmp_path / "cache").glob("*.pcm")
    assert path.read_bytes() == b"abcd"


async def test_lru_eviction_drops_oldest_entries_above_max_bytes(tmp_path) -> None:
    class EchoTts:
        def __init__(self) -> None:
            self.calls = 0

        async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
            self.calls += 1
            yield text.encode("utf-8")

    cache = _cache(tmp_path, EchoTts(), max_bytes=5)
    await _collect(cache.stream("aa", language="sv"))
    await _collect(cache.stream("bbb", language="sv"))
    digest_a = cache_digest(NAMESPACE, "sv", "aa")
    digest_b = cache_digest(NAMESPACE, "sv", "bbb")
    base = time.time()
    os.utime(tmp_path / "cache" / f"{digest_a}.pcm", (base, base))
    os.utime(tmp_path / "cache" / f"{digest_b}.pcm", (base + 10, base + 10))
    await _collect(cache.stream("cc", language="sv"))
    remaining = {path.stem for path in (tmp_path / "cache").glob("*.pcm")}
    assert remaining == {digest_b, cache_digest(NAMESPACE, "sv", "cc")}
    assert cache.stats()["size_bytes"] <= 5


async def test_single_flight_shares_one_synthesis_for_concurrent_misses(tmp_path) -> None:
    class SlowTts:
        def __init__(self) -> None:
            self.calls = 0

        async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
            self.calls += 1
            await asyncio.sleep(0.05)
            yield b"abc"
            yield b"def"

    provider = SlowTts()
    cache = _cache(tmp_path, provider)
    first, second = await asyncio.gather(
        _collect(cache.stream("Hej.", language="sv")),
        _collect(cache.stream("Hej.", language="sv")),
    )
    assert first == second == b"abcdef"
    assert provider.calls == 1
    assert len(list((tmp_path / "cache").glob("*.pcm"))) == 1


async def test_stats_and_clear(tmp_path) -> None:
    cache = _cache(tmp_path, FakeTts([b"ab", b"cd"]), max_bytes=1234)
    await _collect(cache.stream("Ett.", language="sv"))
    await _collect(cache.stream("Två.", language="sv"))
    stats = cache.stats()
    assert stats == {"entries": 2, "size_bytes": 8, "max_bytes": 1234}
    assert cache.clear() == 2
    assert cache.stats()["entries"] == 0
    assert list_tts_cache_entries(tmp_path / "cache") == []


def test_init_sweeps_abandoned_part_files(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    stale = cache_dir / "dead.part"
    stale.write_bytes(b"partial")
    os.utime(stale, (time.time() - 7200,) * 2)
    _cache(tmp_path, FakeTts([b"x"]))
    assert not stale.exists()


def test_stats_sweeps_abandoned_part_files(tmp_path) -> None:
    cache = _cache(tmp_path, FakeTts([b"x"]))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    stale = cache_dir / "dead.part"
    stale.write_bytes(b"partial")
    os.utime(stale, (time.time() - 7200,) * 2)
    fresh = cache_dir / "live.part"
    fresh.write_bytes(b"partial")
    assert cache.stats()["entries"] == 0
    assert not stale.exists()
    assert fresh.exists()


async def test_tts_cache_admin_endpoints(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "tts_cache_dir", str(tmp_path / "cache"))
    cache = _cache(tmp_path, FakeTts([b"ab"]))
    await _collect(cache.stream("Hej.", language="sv"))

    response = await client.get("/tts/cache")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["size_bytes"] == 2
    assert body["entries"][0]["digest"] == cache_digest(NAMESPACE, "sv", "Hej.")

    response = await client.delete("/tts/cache")
    assert response.status_code == 200
    assert response.json() == {"cleared": 1}


async def test_tts_cache_endpoints_require_admin(client) -> None:
    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=USER_USER_ID, email='user@test.local')}"
    )
    response = await client.get("/tts/cache")
    assert response.status_code == 403
    response = await client.delete("/tts/cache")
    assert response.status_code == 403


def test_cached_tts_factory_builds_provider_and_namespaced_cache(tmp_path) -> None:
    calls: dict[str, str] = {}

    class RecordingProvider:
        def __init__(self, **kwargs: str) -> None:
            calls.update(kwargs)

        async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
            yield b"x"

    cache = cached_tts(
        RecordingProvider,
        api_key="key",
        voice_id="voice",
        model_id="model",
        output_format="pcm",
        cache_dir=tmp_path / "cache",
        max_bytes=123,
    )
    assert calls == {
        "api_key": "key",
        "voice_id": "voice",
        "model_id": "model",
        "output_format": "pcm",
    }
    assert cache.stats()["max_bytes"] == 123


async def test_cached_tts_factory_streams_under_the_namespace_key(tmp_path) -> None:
    class SingleChunk:
        def __init__(self, **_kwargs: object) -> None:
            self.calls = 0

        async def stream(self, text: str, *, language: str) -> AsyncIterator[bytes]:
            self.calls += 1
            yield b"x"

    cache = cached_tts(
        SingleChunk,
        api_key="key",
        voice_id="voice",
        model_id="model",
        output_format="pcm",
        cache_dir=tmp_path / "cache",
        max_bytes=1_000_000,
    )
    assert await _collect(cache.stream("Hej.", language="sv")) == b"x"
    namespace = tts_key_namespace(model_id="model", voice_id="voice", output_format="pcm")
    assert (tmp_path / "cache" / f"{cache_digest(namespace, 'sv', 'Hej.')}.pcm").is_file()


def test_module_level_stats_and_clear_match_instance(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    cache = _cache(tmp_path, FakeTts([b"ab"]), max_bytes=999)
    assert tts_cache_stats(cache_dir, max_bytes=999) == {
        "entries": 0,
        "size_bytes": 0,
        "max_bytes": 999,
    }
    assert clear_tts_cache(cache_dir) == 0
    assert cache.stats()["max_bytes"] == 999
