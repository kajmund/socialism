"""Persistent KnowledgeQuestion identity. Not a runtime ResearchNeed."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from app.services.knowledge.scope import (
    SCOPE_SHARED,
    KnowledgeTenantScope,
    customer_scope,
    require_persist_scope,
    shared_scope,
)
from app.services.research.models import ResearchError, ResearchNeed

KnowledgeVisibility = Literal["public", "tenant"]
KNOWLEDGE_VISIBILITIES: tuple[KnowledgeVisibility, ...] = ("public", "tenant")
PUBLIC_NAMESPACE = "public"

EmbeddingMetadata = tuple[str, str, int]


class KnowledgeQuestionError(ResearchError, ValueError):
    """Invalid persistent-question identity or scope."""


@dataclass(frozen=True)
class KnowledgeQuestionScope:
    """Persistent knowledge namespace. Distinct from ResearchContext execution scope.

    ``public`` is a global namespace. ``tenant`` is one customer. Later customers
    get ``tenant:{id}`` without rewriting public rows.
    """

    visibility: KnowledgeVisibility
    customer_id: int | None = None

    def __post_init__(self) -> None:
        if self.visibility not in KNOWLEDGE_VISIBILITIES:
            raise KnowledgeQuestionError(
                f"Unknown KnowledgeQuestion visibility: {self.visibility}"
            )
        if self.visibility == "tenant" and self.customer_id is None:
            raise KnowledgeQuestionError(
                "tenant KnowledgeQuestion requires customer_id"
            )
        if self.visibility == "public" and self.customer_id is not None:
            raise KnowledgeQuestionError(
                "public KnowledgeQuestion cannot carry customer_id"
            )

    @property
    def namespace(self) -> str:
        if self.visibility == "public":
            return PUBLIC_NAMESPACE
        return f"tenant:{self.customer_id}"

    @property
    def tenant(self) -> KnowledgeTenantScope:
        if self.visibility == "public":
            return shared_scope()
        return customer_scope(self.customer_id)


@dataclass(frozen=True)
class KnowledgeQuestion:
    """Canonical persistent question. Execution state stays on runtime needs."""

    id: str
    identity_key: str
    normalized_text: str
    display_text: str
    scope: KnowledgeQuestionScope
    embedding_model: str | None = None
    embedding_version: str | None = None
    embedding_dimension: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.identity_key.strip():
            raise KnowledgeQuestionError("KnowledgeQuestion.identity_key is required")
        if self.embedding_model or self.embedding_version or self.embedding_dimension:
            if (
                not self.embedding_model
                or not self.embedding_version
                or self.embedding_dimension is None
            ):
                raise KnowledgeQuestionError(
                    "embedding model, version, and dimension must be stored together"
                )
            if self.embedding_dimension < 1:
                raise KnowledgeQuestionError("embedding_dimension must be >= 1")


class QuestionIdentityMatcher(Protocol):
    """Optional semantic match after the deterministic identity key misses."""

    @property
    def embedding_metadata(self) -> EmbeddingMetadata | None: ...

    async def index(self, candidates: Sequence[KnowledgeQuestion]) -> None: ...

    async def match(
        self,
        *,
        normalized_text: str,
        identity_key: str,
        candidates: Sequence[KnowledgeQuestion],
    ) -> KnowledgeQuestion | None: ...


class ExactQuestionIdentityMatcher:
    """v1 default: identity_key only. No embeddings, no fuzzy match."""

    @property
    def embedding_metadata(self) -> EmbeddingMetadata | None:
        return None

    async def index(self, candidates: Sequence[KnowledgeQuestion]) -> None:
        del candidates

    async def match(
        self,
        *,
        normalized_text: str,
        identity_key: str,
        candidates: Sequence[KnowledgeQuestion],
    ) -> KnowledgeQuestion | None:
        del normalized_text
        for candidate in candidates:
            if candidate.identity_key == identity_key:
                return candidate
        return None


def normalize_research_question(question: str) -> str:
    """Shared with runtime ``question_key``. Scope is applied separately."""
    return " ".join(question.casefold().split())


def research_question_key(question: str) -> str:
    """Deterministic hash of a normalized question. No embeddings."""
    return hashlib.sha256(normalize_research_question(question).encode("utf-8")).hexdigest()


def knowledge_question_text(question: str) -> str:
    text = normalize_research_question(question)
    if not text:
        raise KnowledgeQuestionError("KnowledgeQuestion text is empty after normalize")
    return text


def knowledge_question_identity_key(question: str) -> str:
    """Same deterministic key as runtime ``question_key``. Scope is applied separately."""
    return research_question_key(knowledge_question_text(question))


def tenant_question_scope(customer_id: int) -> KnowledgeQuestionScope:
    return KnowledgeQuestionScope(visibility="tenant", customer_id=customer_id)


def public_question_scope() -> KnowledgeQuestionScope:
    return KnowledgeQuestionScope(visibility="public")


def lookup_scopes(customer_id: int) -> tuple[KnowledgeQuestionScope, ...]:
    """Tenant namespace plus public. Never another customer."""
    require_persist_scope(customer_id=customer_id)
    return (tenant_question_scope(customer_id), public_question_scope())


def question_scope_from_tenant(scope: KnowledgeTenantScope) -> KnowledgeQuestionScope:
    if scope.scope_type == SCOPE_SHARED:
        return public_question_scope()
    return tenant_question_scope(scope.customer_id)


def tenant_from_question_scope(scope: KnowledgeQuestionScope) -> KnowledgeTenantScope:
    return scope.tenant


def evidence_visibility(metadata: dict[str, object] | None) -> KnowledgeVisibility:
    """Public reuse only when provenance says so. Do not infer from source_type."""
    raw = metadata or {}
    if raw.get("public") is True:
        return "public"
    for key in ("visibility", "scope"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip().casefold() == "public":
            return "public"
    return "tenant"


def stable_evidence_ref(
    *,
    provider: str | None,
    source_id: str | None,
    locator: str | None,
    excerpt: str | None,
) -> str:
    """Need-independent reference. Documents stay in EvidenceSet storage."""
    excerpt_hash = hashlib.sha256((excerpt or "").encode("utf-8")).hexdigest()
    payload = "\x1f".join(
        (provider or "", source_id or "", locator or "", excerpt_hash)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def question_from_need(
    need: ResearchNeed,
    *,
    question_id: str,
    scope: KnowledgeQuestionScope,
    embedding: EmbeddingMetadata | None = None,
) -> KnowledgeQuestion:
    display = need.question.strip()
    normalized = knowledge_question_text(display)
    model, version, dimension = embedding if embedding else (None, None, None)
    return KnowledgeQuestion(
        id=question_id,
        identity_key=knowledge_question_identity_key(display),
        normalized_text=normalized,
        display_text=display,
        scope=scope,
        embedding_model=model,
        embedding_version=version,
        embedding_dimension=dimension,
    )


@dataclass(frozen=True)
class QuestionIdentity:
    identity_key: str
    normalized_text: str
    display_text: str
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", dict(self.extra))


def identity_from_text(question: str) -> QuestionIdentity:
    display = question.strip()
    normalized = knowledge_question_text(display)
    return QuestionIdentity(
        identity_key=knowledge_question_identity_key(display),
        normalized_text=normalized,
        display_text=display,
    )
