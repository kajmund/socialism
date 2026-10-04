"""KnowledgeProvider adapter. Reuses knowledge tenant checks; does not widen them."""

from __future__ import annotations

from dataclasses import replace

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

_KNOWLEDGE_SOURCE_TYPES = frozenset({"case_knowledge", "customer_knowledge", "domain_knowledge"})
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
                f"{source_type} is not a document-knowledge adapter; "
                "do not bind it to KnowledgeProvider"
            )
        self.source_type = source_type
        self._provider = provider

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    @property
    def shared_db_session(self) -> object | None:
        return getattr(self._provider, "shared_db_session", None)

    async def research(
        self,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        scope = search_scope(self.source_type, context)
        hits = await self._provider.search(
            KnowledgeQuery(query=need.question, scope=scope, limit=context.limit, filters={"scope_type": "shared" if self.source_type == "domain_knowledge" else "customer"})
        )
        hits = [hit for hit in hits if _appropriate_scope(hit, self.source_type)]
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
        if not scope.case_id and not scope.workspace_id:
            raise ResearchScopeRequiredError("case_knowledge requires workspace_id or case_id")
        narrowed = replace(scope)
        _refuse_widened_scope(scope, narrowed)
        return narrowed
    if source_type == "customer_knowledge":
        narrowed = replace(scope, case_id=None)
        _refuse_widened_scope(scope, narrowed)
        return narrowed
    if source_type == "domain_knowledge":
        return replace(scope, case_id=None, module=None, workspace_id=None,
                       readable_workspace_ids=(), allowed_source_object_ids=None,
                       allowed_document_version_ids=None)
    raise ResearchScopeRequiredError(
        f"{source_type} has no Knowledge adapter; refusing customer_id=None fallback"
    )


def _appropriate_scope(hit: KnowledgeHit, source_type: ResearchSourceType) -> bool:
    if source_type == "domain_knowledge":
        return hit.metadata.get("scope_type") == "shared"
    return hit.metadata.get("scope_type") != "shared"


def _refuse_widened_scope(supplied: KnowledgeScope, used: KnowledgeScope) -> None:
    if used.customer_id != supplied.customer_id:
        raise ResearchScopeRequiredError("refusing to change customer_id")
    if supplied.case_id is None and used.case_id is not None:
        raise ResearchScopeRequiredError("refusing to invent case_id")
    if (
        supplied.case_id is not None
        and used.case_id is not None
        and used.case_id != supplied.case_id
    ):
        raise ResearchScopeRequiredError("refusing to change case_id")


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
        if isinstance(value, str) and value.startswith(("http://", "https://", "/underlag/")):
            return value
    return None
