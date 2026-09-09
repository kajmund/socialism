"""Provider-neutral knowledge models. No storage-path document ids."""

from __future__ import annotations

from dataclasses import dataclass, field


class KnowledgeScopeRequiredError(ValueError):
    """Retrieval requires a non-empty scope; global search is not allowed."""


@dataclass(frozen=True)
class KnowledgeScope:
    customer_id: int | None = None
    case_id: str | None = None
    module: str | None = None

    def is_empty(self) -> bool:
        return self.customer_id is None and self.case_id is None and self.module is None


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
    if scope.is_empty():
        raise KnowledgeScopeRequiredError(
            "Knowledge retrieval requires scope (customer_id, case_id, or module)"
        )


def scope_of(
    *,
    customer_id: int | None,
    case_id: str | None,
    module: str | None,
) -> KnowledgeScope:
    return KnowledgeScope(customer_id=customer_id, case_id=case_id, module=module)


def scope_allows(*, owned: KnowledgeScope, requested: KnowledgeScope) -> bool:
    """Fail closed: every field set on the request must match the record."""
    if requested.is_empty():
        return False
    if requested.customer_id is not None and owned.customer_id != requested.customer_id:
        return False
    if requested.case_id is not None and owned.case_id != requested.case_id:
        return False
    if requested.module is not None and owned.module != requested.module:
        return False
    return True
