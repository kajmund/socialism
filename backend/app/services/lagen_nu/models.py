"""Normalized official lagen.nu MCP payloads. No research routing here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LagenNuPin:
    uri: str | None
    pinpoint: str | None
    label: str | None
    highlight: tuple[str, ...] = ()


@dataclass(frozen=True)
class LagenNuSearchHit:
    id: str | None
    uri: str | None
    url: str | None
    title: str | None
    identifier: str | None
    source: str | None
    kind: str | None
    score: float | None
    inbound_count: int | None
    pin: LagenNuPin | None
    fragments: tuple[LagenNuPin, ...] = ()
    highlight: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResults:
    query: str
    total: int
    results: tuple[LagenNuSearchHit, ...] = ()


@dataclass(frozen=True)
class RecognizedCitation:
    uri: str | None
    source: str | None
    invalid: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedCitations:
    results: tuple[LagenNuSearchHit, ...] = ()
    recognized: tuple[RecognizedCitation, ...] = ()


@dataclass(frozen=True)
class IncomingCitations:
    uri: str
    total: int
    results: tuple[LagenNuSearchHit, ...] = ()


@dataclass(frozen=True)
class LagenNuDocument:
    uri: str
    title: str | None
    text: str
    source: str | None
    kind: str | None
    label: str | None
    publisher_source_url: str | None
    pinpoint: str | None
    truncated: bool
    inbound_count: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
