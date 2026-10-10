"""Stable graph records. OverGraph u64 ids are local; `key` is the identity."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.services.knowledge.scope import KnowledgeTenantScope


@dataclass(frozen=True)
class GraphRecord:
    key: str
    labels: tuple[str, ...]
    props: dict[str, object]
    engine_id: int | None = None
    dense_vector: tuple[float, ...] | None = None


@dataclass(frozen=True)
class TextUnitWrite:
    unit_id: str
    scope: KnowledgeTenantScope
    document_id: str
    document_version_id: str
    text: str
    content_hash: str
    ordinal: int
    section_id: str | None = None
    locator: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    ingested_at: datetime | None = None
    embedding: tuple[float, ...] | None = None
    next_id: str | None = None


@dataclass
class GraphFactView:
    """Research-facing fact. `id` is the OverGraph key (Graph v2 identity)."""

    id: str
    scope_key: str
    source_id: str
    target_id: str
    predicate: str
    fact_text: str
    status: str
    customer_id: int | None = None
    context_id: str | None = None
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    attributes: dict[str, object] = field(default_factory=dict)
    text_unit_refs: tuple[str, ...] = ()
    created_at: datetime | None = None


@dataclass(frozen=True)
class TextUnitView:
    id: str
    document_id: str
    document_version_id: str
    scope_key: str
    scope_type: str
    text: str
    content_hash: str
    ordinal: int
    customer_id: int | None = None
    locator: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeHit:
    key: str
    kind: Literal["fact", "text_unit", "entity"]
    score: float
    scope_key: str
    text: str
    props: dict[str, object] = field(default_factory=dict)
    hop: int = 0
