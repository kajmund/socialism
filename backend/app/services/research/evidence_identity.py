"""Provider-neutral canonical document and passage identities."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit


def canonical_source_identity(source_id: str | None, source_url: str | None) -> str:
    raw = (source_id or source_url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        return raw.split("#", 1)[0]
    parts = urlsplit(raw)
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            parts.query,
            "",
        )
    )


def evidence_source_id(
    *,
    provider: str | None,
    source_id: str | None,
    source_url: str | None,
    content_hash: str,
) -> str:
    identity = canonical_source_identity(source_id, source_url) or f"content:{content_hash}"
    return hashlib.sha256(f"{provider or ''}\x1f{identity}".encode()).hexdigest()


def evidence_passage_id(
    *,
    source_key: str,
    source_id: str | None,
    locator: str | None,
    content_hash: str,
) -> str:
    payload = "\x1f".join((source_key, source_id or "", locator or "", content_hash))
    return hashlib.sha256(payload.encode()).hexdigest()
