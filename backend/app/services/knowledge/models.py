"""Provider-neutral knowledge models. No storage-path document ids."""

from __future__ import annotations

from dataclasses import dataclass, field


class KnowledgeScopeRequiredError(ValueError):
    """Retrieval requires a kund. Module-only or empty scope is not allowed."""


@dataclass(frozen=True)
class KnowledgeScope:
    customer_id: int | None = None
    case_id: str | None = None
    module: str | None = None


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    provider: str
    external_id: str
    title: str
    mime_type: str
    scope: KnowledgeScope
    version: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeQuery:
    query: str
    scope: KnowledgeScope
    limit: int = 10

    def __post_init__(self) -> None:
        require_scope(self.scope)
        if self.limit < 1:
            raise ValueError("KnowledgeQuery.limit must be >= 1")


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
    """Vector-store unit. Ingest (parse/embed) is a later PR."""

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
    metadata: dict[str, object] = field(default_factory=dict)


def require_scope(scope: KnowledgeScope) -> None:
    if scope.customer_id is None:
        raise KnowledgeScopeRequiredError(
            "Knowledge retrieval requires customer_id; module-only scope cannot cross kunders"
        )


def scope_of(
    *,
    customer_id: int | None,
    case_id: str | None,
    module: str | None,
) -> KnowledgeScope:
    return KnowledgeScope(customer_id=customer_id, case_id=case_id, module=module)


def scope_allows(*, owned: KnowledgeScope, requested: KnowledgeScope) -> bool:
    """Fail closed: kund is required; other set fields must match the record."""
    if requested.customer_id is None or owned.customer_id != requested.customer_id:
        return False
    return _field_allows(owned.case_id, requested.case_id) and _field_allows(
        owned.module, requested.module
    )


def _field_allows[T](owned: T | None, requested: T | None) -> bool:
    return requested is None or owned == requested
