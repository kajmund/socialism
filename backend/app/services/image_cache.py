"""SHA256-keyed image + vision caption cache for budskapsverkstaden."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.config import settings
from app.llm.vision import complete_vision_text
from app.services.image_caption import rich_caption_prompt
from app.services.playground_image import ALLOWED_IMAGE_TYPES, validate_image
from app.services.playground_image_models import resolve_vision_selection

Locale = Literal["sv", "en"]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cache_root() -> Path:
    return Path(settings.image_cache_dir)


def _entries_dir() -> Path:
    return _cache_root() / "entries"


def _meta_path(digest: str) -> Path:
    return _entries_dir() / f"{digest}.json"


def _bytes_path(digest: str) -> Path:
    return _entries_dir() / f"{digest}.bin"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_meta(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_meta(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_entry(digest: str) -> dict[str, Any] | None:
    normalized = digest.strip().lower()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        return None
    meta = _read_meta(_meta_path(normalized))
    if meta is None:
        return None
    if not _bytes_path(normalized).is_file():
        return None
    return meta


def list_entries() -> list[dict[str, Any]]:
    root = _entries_dir()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        digest = path.stem
        meta = _read_meta(path)
        if meta is None or not _bytes_path(digest).is_file():
            continue
        out.append(meta)
    out.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return out


def delete_entry(digest: str) -> bool:
    normalized = digest.strip().lower()
    meta_path = _meta_path(normalized)
    bin_path = _bytes_path(normalized)
    if not meta_path.is_file() and not bin_path.is_file():
        return False
    if meta_path.is_file():
        meta_path.unlink()
    if bin_path.is_file():
        bin_path.unlink()
    return True


def clear_image_cache() -> int:
    root = _entries_dir()
    if not root.is_dir():
        return 0
    count = len(list(root.glob("*.json")))
    shutil.rmtree(root)
    return count


def image_bytes_path(digest: str) -> Path | None:
    path = _bytes_path(digest.strip().lower())
    return path if path.is_file() else None


def update_caption(digest: str, caption: str) -> dict[str, Any]:
    text = caption.strip()
    if not text:
        raise ValueError("Caption must not be empty")
    meta = get_entry(digest)
    if meta is None:
        raise ValueError(f"Image cache entry {digest!r} not found")
    meta["caption"] = text
    meta["caption_edited"] = True
    meta["updated_at"] = _now_iso()
    _write_meta(_meta_path(digest.strip().lower()), meta)
    return meta


async def ensure_cached_image(
    image_bytes: bytes,
    *,
    content_type: str,
    locale: Locale = "sv",
    vision_provider: str | None = None,
    vision_model: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Store image + caption. Returns (entry, cache_hit)."""
    mime = validate_image(content_type=content_type, size_bytes=len(image_bytes))
    digest = sha256_hex(image_bytes)
    existing = get_entry(digest)
    if existing is not None:
        return existing, True

    provider, model_id = resolve_vision_selection(
        provider=vision_provider,
        model=vision_model,
    )
    caption = await complete_vision_text(
        image_bytes=image_bytes,
        content_type=mime,
        prompt=rich_caption_prompt(locale),
        provider=provider,
        model=model_id,
    )
    now = _now_iso()
    meta: dict[str, Any] = {
        "sha256": digest,
        "caption": caption.strip(),
        "content_type": mime,
        "size_bytes": len(image_bytes),
        "vision_provider": provider,
        "vision_model": model_id,
        "caption_edited": False,
        "created_at": now,
        "updated_at": now,
    }
    _bytes_path(digest).parent.mkdir(parents=True, exist_ok=True)
    _bytes_path(digest).write_bytes(image_bytes)
    _write_meta(_meta_path(digest), meta)
    return meta, False


def compose_feed_body(*, body: str, caption: str | None) -> str:
    """Build injection-ready text from optional follow text + image caption."""
    text = body.strip()
    cap = (caption or "").strip()
    if cap and text:
        return f"{text}\n\n[Bild: {cap}]"
    if cap:
        return cap
    return text
