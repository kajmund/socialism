"""KnowledgeProvider adapter. Reuses knowledge tenant checks; does not widen them."""

from __future__ import annotations

from app.services.knowledge.models import KnowledgeHit, KnowledgeQuery, KnowledgeScope
from app.services.knowledge.provider import KnowledgeProvider
from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    ResearchScopeRequiredError,
    ResearchSourceType,
    research_evidence,
)

_KNOWLEDGE_SOURCE_TYPES = frozenset({"case_knowledge", "customer_knowledge"})
_BLOCKED_METADATA_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "local_path",
        "storage_bucket",
        "storage_key",
        "storage_path",
        "token",
    }
)


class KnowledgeResearchSource:
    def __init__(self, provider: KnowledgeProvider, *, source_type: ResearchSourceType) -> None:
        if source_type not in _KNOWLEDGE_SOURCE_TYPES:
            raise ValueError(
                f"{source_type} is not a private-knowledge adapter; "
                "do not bind it to KnowledgeProvider"
            )
        self.source_type = source_type
        self._provider = provider

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    async def research(
        self,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        scope = search_scope(self.source_type, context)
        hits = await self._provider.search(
            KnowledgeQuery(query=need.question, scope=scope, limit=context.limit)
        )
        if not hits:
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type=self.source_type,
                    status="not_found",
                    provider=self.provider_id,
                )
            ]
        return [self._from_hit(need, hit) for hit in hits]

    def _from_hit(self, need: ResearchNeed, hit: KnowledgeHit) -> ResearchEvidence:
        metadata = provenance_from_hit(hit)
        return research_evidence(
            research_need_id=need.id,
            source_type=self.source_type,
            status="found",
            title=hit.title,
            excerpt=hit.excerpt,
            locator=hit.locator,
            source_id=hit.document_id,
            source_url=_public_url(hit.metadata),
            provider=hit.provider,
            score=hit.score,
            metadata=metadata,
        )


def search_scope(source_type: ResearchSourceType, context: ResearchContext) -> KnowledgeScope:
    """Build the KnowledgeQuery scope. Never changes customer_id."""
    scope = context.scope
    if scope.customer_id is None:
        raise ResearchScopeRequiredError("private knowledge requires customer_id")
    if source_type == "case_knowledge":
        if not scope.case_id:
            raise ResearchScopeRequiredError("case_knowledge requires case_id")
        return KnowledgeScope(
            customer_id=scope.customer_id,
            case_id=scope.case_id,
            module=scope.module,
        )
    if source_type == "customer_knowledge":
        return KnowledgeScope(
            customer_id=scope.customer_id,
            case_id=None,
            module=scope.module,
        )
    raise ResearchScopeRequiredError(
        f"{source_type} has no Knowledge adapter; refusing customer_id=None fallback"
    )


def provenance_from_hit(hit: KnowledgeHit) -> dict[str, object]:
    """document_id + locator + version matter more than a public URL."""
    metadata: dict[str, object] = {
        key: value
        for key, value in hit.metadata.items()
        if key not in _BLOCKED_METADATA_KEYS
    }
    metadata["document_id"] = hit.document_id
    if hit.external_id is not None:
        metadata.setdefault("external_id", hit.external_id)
    if hit.locator is not None:
        metadata.setdefault("locator", hit.locator)
    if hit.provider:
        metadata.setdefault("provider", hit.provider)
    return metadata


def _public_url(metadata: dict[str, object]) -> str | None:
    for key in ("source_url", "url"):
        value = metadata.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None
