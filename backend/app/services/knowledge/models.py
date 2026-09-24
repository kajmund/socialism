"""Provider-neutral knowledge models. No storage-path document ids."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeScopeError,
    KnowledgeTenantScope,
    object_scope,
    visible_to,
)


class KnowledgeScopeRequiredError(ValueError):
    """Private/customer knowledge requires a kund tenant boundary."""


@dataclass(frozen=True)
class KnowledgeScope:
    """Reader or persist scope. Retrieval still requires a customer reader.

    Persist may use ``scope_type='shared'`` with ``customer_id=None``.
    case_id and module only narrow further. Shared knowledge is explicit.
    """

    customer_id: int | None = None
    case_id: str | None = None
    module: str | None = None
    scope_type: str = SCOPE_CUSTOMER

    def __post_init__(self) -> None:
        try:
            object_scope(self.scope_type, self.customer_id)
        except KnowledgeScopeError as exc:
            raise KnowledgeScopeRequiredError(str(exc)) from exc

    @property
    def tenant(self) -> KnowledgeTenantScope:
        return object_scope(self.scope_type, self.customer_id)


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    provider: str
    external_id: str
    title: str
    mime_type: str
    scope: KnowledgeScope
    version: str | None = None
    source_type: str | None = None
    canonical_uri: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeQuery:
    query: str
    scope: KnowledgeScope
    limit: int = 10
    filters: dict[str, str | int | float | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_scope(self.scope)
        if self.limit < 1:
            raise ValueError("KnowledgeQuery.limit must be >= 1")
        object.__setattr__(self, "filters", dict(self.filters))


@dataclass(frozen=True)
class KnowledgeHit:
    document_id: str
    provider: str
    title: str
    excerpt: str
    score: float | None = None
    locator: str | None = None
    external_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeChunk:
    """Vector-store unit produced by ingest. Embeddings live on EmbeddedKnowledgeChunk."""

    document_id: str
    chunk_id: str
    text: str
    customer_id: int | None
    case_id: str | None
    module: str | None
    title: str
    locator: str | None = None
    provider: str | None = None
    version: str | None = None
    content_hash: str | None = None
    scope_type: str = SCOPE_CUSTOMER
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object_scope(self.scope_type, self.customer_id)


@dataclass(frozen=True)
class EmbeddedKnowledgeChunk:
    """Chunk plus an explicit embedding. VectorStore stores; EmbeddingProvider creates."""

    chunk: KnowledgeChunk
    embedding: list[float]


@dataclass(frozen=True)
class EmbeddedKnowledgeQuery:
    """Query plus an explicit embedding. VectorStore searches vectors, not raw text."""

    query: KnowledgeQuery
    embedding: list[float]

    def __post_init__(self) -> None:
        if not self.embedding:
            raise ValueError("EmbeddedKnowledgeQuery.embedding must not be empty")


def require_scope(scope: KnowledgeScope) -> None:
    """Reader scope: retrieval is always as a customer. Shared is not a reader."""
    if scope.scope_type != SCOPE_CUSTOMER or scope.customer_id is None:
        raise KnowledgeScopeRequiredError(
            "Knowledge retrieval requires customer_id; module or case alone is not a tenant"
        )


def scope_of(
    *,
    customer_id: int | None,
    case_id: str | None,
    module: str | None,
    scope_type: str = SCOPE_CUSTOMER,
) -> KnowledgeScope:
    return KnowledgeScope(
        customer_id=customer_id,
        case_id=case_id,
        module=module,
        scope_type=scope_type,
    )


def scope_allows(*, owned: KnowledgeScope, requested: KnowledgeScope) -> bool:
    """Fail closed: reader kund is required; shared records are visible to every customer."""
    require_scope(requested)
    if not visible_to(owned=owned.tenant, reader_customer_id=requested.customer_id):
        return False
    return _field_allows(owned.case_id, requested.case_id) and _field_allows(
        owned.module, requested.module
    )


def _field_allows[T](owned: T | None, requested: T | None) -> bool:
    return requested is None or owned == requested
