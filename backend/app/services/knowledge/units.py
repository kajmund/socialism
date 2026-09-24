"""Canonical Document → Section → TextUnit. Domain-neutral knowledge atoms."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_section_id(
    *,
    document_id: str,
    version: str | None,
    path: str,
) -> str:
    payload = f"{document_id}\0{version or ''}\0{path}".encode()
    return hashlib.sha256(payload).hexdigest()


def make_text_unit_id(
    *,
    document_id: str,
    version: str | None,
    locator: str | None,
    content_hash: str,
) -> str:
    payload = f"{document_id}\0{version or ''}\0{locator or ''}\0{content_hash}".encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CanonicalDocument:
    """A citable source. Deduplicate on (source_type, canonical_uri, version)."""

    id: str
    source_type: str
    canonical_uri: str
    title: str
    content_hash: str
    mime_type: str
    version: str | None = None
    domain: str | None = None
    jurisdiction: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    ingested_at: datetime | None = None
    superseded_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentSection:
    """Hierarchical structural region inside a CanonicalDocument."""

    id: str
    document_id: str
    parent_section_id: str | None
    ordinal: int
    type: str
    title: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TextUnit:
    """Canonical passage. Everything the system reasons from grounds here."""

    id: str
    document_id: str
    section_id: str | None
    ordinal: int
    text: str
    content_hash: str
    locator: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    ingested_at: datetime | None = None
    embedding_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentedDocument:
    document: CanonicalDocument
    sections: tuple[DocumentSection, ...]
    text_units: tuple[TextUnit, ...]
