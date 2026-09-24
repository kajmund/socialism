"""Canonical Document → DocumentVersion → Section → TextUnit. Domain-neutral."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_document_version_id() -> str:
    """Unique per temporal occurrence. Same content may recur; the id may not."""
    return uuid.uuid4().hex


def make_section_id(*, document_version_id: str, path: str) -> str:
    payload = f"{document_version_id}\0{path}".encode()
    return hashlib.sha256(payload).hexdigest()


def make_text_unit_id(
    *,
    document_version_id: str,
    locator: str | None,
    content_hash: str,
) -> str:
    payload = f"{document_version_id}\0{locator or ''}\0{content_hash}".encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CanonicalDocument:
    """Stable source identity. Deduplicate on (source_type, canonical_uri)."""

    id: str
    source_type: str
    canonical_uri: str
    title: str
    domain: str | None = None
    jurisdiction: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentVersion:
    """Immutable content snapshot of a CanonicalDocument."""

    id: str
    document_id: str
    content_hash: str
    mime_type: str
    version: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    ingested_at: datetime | None = None
    superseded_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentSection:
    """Hierarchical structural region inside a DocumentVersion."""

    id: str
    document_version_id: str
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
    document_version_id: str
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
    version: DocumentVersion
    sections: tuple[DocumentSection, ...]
    text_units: tuple[TextUnit, ...]
