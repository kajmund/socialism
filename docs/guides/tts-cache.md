# TTS cache (phrase level)

Disk cache in front of the ElevenLabs streaming TTS used by live voice
(`LiveSpeechRuntime` and `GroupVoiceAudioRuntime`). It removes provider calls
for phrases that have already been synthesized. The cache is pure disk I/O —
no database is involved, so it is safe to use while a turn's database session
is open.

## What is cached

`SpeechSegmenter` already splits streamed reply text into short normalized
phrases (roughly 110–220 characters) before they reach TTS. Those phrases are
the cache unit: one cache entry holds the raw PCM bytes (as returned by
`ElevenLabsTts.stream`) for one phrase. Text is cached only in its
post-segmentation, normalized form, so cache hits also skip the provider for
the exact same spoken phrase later in the session or in future sessions.

Word-level caching (concatenating audio for individual words) is a separate
question that is being investigated in
[tts-word-cache.md](tts-word-cache.md); this cache deliberately works at
phrase granularity.

## Key

A cache key is the SHA-256 hex digest of

```text
{namespace}\x00{language}\x00{text}
```

where `namespace` is `"{model_id}|{voice_id}|{output_format}"` (built by
`tts_key_namespace`). Provider configuration is therefore part of the key:
changing the voice, model, or output format misses cleanly instead of serving
audio from the old configuration. The runtimes build their cache through the
`cached_tts` factory in `app/services/tts_cache.py`, which constructs the
provider and derives the namespace, so call sites never repeat the key
formula. The factory takes the provider class as a callable so tests can
still monkeypatch it at the caller's module boundary. The group voice runtime
keeps one `CachedTts` per voice in its existing per-voice dict.

## Storage layout

Under the configured directory (`TTS_CACHE_DIR`, default `data/tts_cache`
relative to the backend working directory):

- `{digest}.pcm` — a complete, committed cache entry.
- `{digest}.{uuid}.part` — the temporary file for an in-progress synthesis.

On a miss, chunks are streamed from the provider and teed into the `.part`
file. Empty chunks are skipped. On normal completion the temp file is moved
into place with `os.replace`, so readers only ever see complete entries.
On cancellation (`CancelledError`) or a provider error the temp file is
deleted, nothing is cached, and the error propagates unchanged — there is no
fallback and no partial entry.

On a hit, the whole file is read and yielded in 64 KiB chunks; no file handle
is held across awaits.

Abandoned `.part` files (from crashed or cancelled syntheses) older than one
hour are swept at `CachedTts` construction and on every `stats()` call.

## Single-flight

Two concurrent misses for the same key share one synthesis: the second caller
waits on an `asyncio.Event` keyed by digest and then reads the finished file.
If the leader fails, the waiter simply becomes the next leader and retries the
provider (errors still propagate to the original caller).

## Size limit and eviction

`TTS_CACHE_MAX_BYTES` (default 512 MiB) caps the total size of `.pcm` entries.
After every successful store the cache evicts the oldest entries by file
mtime until the total is at or below the limit. A hit does not touch the
file, so mtime is effectively store time and eviction is oldest-written
first.

## Config

| Variable | Default | Notes |
| -------- | ------- | ----- |
| `TTS_CACHE_DIR` | `data/tts_cache` | Relative to the backend working directory |
| `TTS_CACHE_MAX_BYTES` | `536870912` | 512 MiB; must be at least 1 MiB |

Both fields are defined on the `LiveSpeechSettings` mixin in
`app/live_speech_settings.py` (like the other `live_speech_tts_*` settings)
and are inherited by `Settings` in `app/config.py`; `app/config.py` is pinned
at its 500-line maintainability cap, so new live-speech settings are added to
the mixin instead of growing it.

## Admin endpoints

Both require an admin user (`require_admin`):

- `GET /tts/cache` — stats (`count`, `size_bytes`, `max_bytes`, `cache_dir`)
  plus the entry list (digest, size, modified time).
- `DELETE /tts/cache` — removes all entries and temp files, returns
  `{ "cleared": n }`.

## Tests

`tests/test_tts_cache.py` covers hit/miss persistence, key isolation,
cancellation and error semantics, LRU eviction, single-flight, stale-part
sweeps, clear/stats, and the admin endpoints — all offline with a fake
provider.
