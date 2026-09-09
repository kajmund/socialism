"""Reusable research-need / evidence models. No panel or LLM types."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from app.services.knowledge.models import KnowledgeScope, require_scope

ResearchSourceType = Literal[
    "case_knowledge",
    "customer_knowledge",
    "domain_knowledge",
    "swedish_law",
    "swedish_preparatory_works",
    "web",
]

RESEARCH_SOURCE_TYPES: tuple[ResearchSourceType, ...] = (
    "case_knowledge",
    "customer_knowledge",
    "domain_knowledge",
    "swedish_law",
    "swedish_preparatory_works",
    "web",
)

EvidenceStatus = Literal["found", "not_found", "error"]


class ResearchError(Exception):
    """Base error for the research layer."""


class ResearchScopeRequiredError(ResearchError, ValueError):
    """Private knowledge sources refuse to run without the required tenant fields."""


class ResearchSourceNotRegisteredError(ResearchError):
    def __init__(self, source_type: str) -> None:
        super().__init__(f"No research source registered for source_type={source_type}")
        self.source_type = source_type


@dataclass(frozen=True)
class ResearchNeed:
    id: str
    question: str
    why_needed: str
    requested_by: list[str] = field(default_factory=list)
    source_types: list[ResearchSourceType] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_by", list(self.requested_by))
        object.__setattr__(self, "source_types", list(self.source_types))


@dataclass(frozen=True)
class ResearchContext:
    """Tenant/case/module scope plus an optional hit limit.

    Sources may narrow this scope (drop case for customer_knowledge) but
    must never change customer_id or invent a wider tenant.
    """

    scope: KnowledgeScope
    limit: int = 10

    def __post_init__(self) -> None:
        require_scope(self.scope)
        if self.limit < 1:
            raise ValueError("ResearchContext.limit must be >= 1")


@dataclass(frozen=True)
class ResearchEvidence:
    evidence_id: str
    research_need_id: str
    source_type: ResearchSourceType
    status: EvidenceStatus
    title: str | None
    excerpt: str | None
    locator: str | None
    source_id: str | None
    source_url: str | None
    provider: str | None
    score: float | None
    retrieved_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_evidence_id(
    *,
    research_need_id: str,
    source_type: str,
    status: EvidenceStatus,
    provider: str | None = None,
    source_id: str | None = None,
    locator: str | None = None,
    excerpt: str | None = None,
) -> str:
    """Stable id from need + source + locator + excerpt hash. No LLM involved."""
    excerpt_hash = hashlib.sha256((excerpt or "").encode("utf-8")).hexdigest()
    payload = "\x1f".join(
        (
            research_need_id,
            source_type,
            status,
            provider or "",
            source_id or "",
            locator or "",
            excerpt_hash,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def research_evidence(
    *,
    research_need_id: str,
    source_type: ResearchSourceType,
    status: EvidenceStatus,
    title: str | None = None,
    excerpt: str | None = None,
    locator: str | None = None,
    source_id: str | None = None,
    source_url: str | None = None,
    provider: str | None = None,
    score: float | None = None,
    retrieved_at: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id=make_evidence_id(
            research_need_id=research_need_id,
            source_type=source_type,
            status=status,
            provider=provider,
            source_id=source_id,
            locator=locator,
            excerpt=excerpt,
        ),
        research_need_id=research_need_id,
        source_type=source_type,
        status=status,
        title=title,
        excerpt=excerpt,
        locator=locator,
        source_id=source_id,
        source_url=source_url,
        provider=provider,
        score=score,
        retrieved_at=retrieved_at or utc_now(),
        metadata=metadata or {},
    )
