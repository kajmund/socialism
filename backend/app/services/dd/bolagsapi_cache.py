"""Disk cache for BolagsAPI MCP tool results. TTL is 10 months."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import settings

CACHE_TTL = timedelta(days=304)


def _cache_dir() -> Path:
    return Path(settings.bolagsapi_cache_dir)


def _entries_dir() -> Path:
    return _cache_dir() / "entries"


def cache_id(kind: str, payload: dict[str, Any]) -> str:
    blob = json.dumps(
        {"kind": kind, **payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _entry_path(entry_id: str) -> Path:
    return _entries_dir() / f"{entry_id}.json"


def _parse_expires(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def get_cached(kind: str, payload: dict[str, Any], *, now: datetime | None = None) -> str | None:
    entry_id = cache_id(kind, payload)
    path = _entry_path(entry_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Corrupt BolagsAPI cache entry {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Corrupt BolagsAPI cache entry {path.name}: not an object")
    expires = _parse_expires(raw.get("expires_at"))
    moment = now or datetime.now(UTC)
    if expires is None or expires <= moment:
        path.unlink(missing_ok=True)
        return None
    value = raw.get("value")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Corrupt BolagsAPI cache entry {path.name}: missing value")
    return value


def put_cached(
    kind: str,
    payload: dict[str, Any],
    value: str,
    *,
    now: datetime | None = None,
) -> None:
    text = value.strip()
    if not text:
        raise ValueError("Refusing to cache empty BolagsAPI content")
    if "rate limit" in text.lower():
        raise ValueError("Refusing to cache BolagsAPI rate-limit responses")
    moment = now or datetime.now(UTC)
    entry_id = cache_id(kind, payload)
    path = _entry_path(entry_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": entry_id,
                "kind": kind,
                "stored_at": moment.isoformat(),
                "expires_at": (moment + CACHE_TTL).isoformat(),
                "value": value,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_bolagsapi_cache() -> int:
    entries = _entries_dir()
    if not entries.is_dir():
        return 0
    removed = 0
    for path in entries.glob("*.json"):
        path.unlink()
        removed += 1
    return removed
