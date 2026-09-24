"""Canonical lagen.nu URI helpers."""

from __future__ import annotations

_CANONICAL_PREFIX = "https://lagen.nu/"
_HTTP_PREFIX = "http://lagen.nu/"
_FERENDA_HTTPS = "https://ferenda.lagen.nu/"
_FERENDA_HTTP = "http://ferenda.lagen.nu/"


def canonical_lagen_nu_uri(value: object) -> str | None:
    """Return a https://lagen.nu/ URI, or None if the value is not lagen.nu."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.startswith(_FERENDA_HTTPS):
        text = _CANONICAL_PREFIX + text[len(_FERENDA_HTTPS) :]
    elif text.startswith(_FERENDA_HTTP):
        text = _CANONICAL_PREFIX + text[len(_FERENDA_HTTP) :]
    elif text.startswith(_HTTP_PREFIX):
        text = _CANONICAL_PREFIX + text[len(_HTTP_PREFIX) :]
    if not text.startswith(_CANONICAL_PREFIX):
        return None
    path = text[len(_CANONICAL_PREFIX) :]
    if not path or path.startswith(("/", "?")):
        return None
    return text


def canonical_lagen_nu_document_uri(value: object) -> str | None:
    """Document identity URI without a pinpoint fragment.

    Evidence items may keep `#pinpoint` via `compose_canonical_uri`.
    CanonicalDocument identity must not.
    """
    uri = canonical_lagen_nu_uri(value)
    if uri is None:
        return None
    document_uri = uri.split("#", 1)[0]
    path = document_uri[len(_CANONICAL_PREFIX) :]
    if not path or path.startswith(("/", "?")):
        return None
    return document_uri


def compose_canonical_uri(uri: str, pinpoint: str | None) -> str:
    if pinpoint and "#" not in uri:
        return f"{uri}#{pinpoint}"
    return uri
