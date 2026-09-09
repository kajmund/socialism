"""Register / get / list knowledge providers. This PR registers supabase only."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.provider import (
    KnowledgeProvider,
    KnowledgeProviderNotFoundError,
)
from app.services.knowledge.supabase_provider import SupabaseKnowledgeProvider
from app.services.knowledge.vector_store import KnowledgeVectorStore


class KnowledgeProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, KnowledgeProvider] = {}

    def register(self, provider: KnowledgeProvider) -> None:
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> KnowledgeProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KnowledgeProviderNotFoundError(provider_id) from exc

    def list_ids(self) -> list[str]:
        return sorted(self._providers)


def build_knowledge_registry(
    session: AsyncSession,
    vector_store: KnowledgeVectorStore,
    embeddings: EmbeddingProvider,
) -> KnowledgeProviderRegistry:
    registry = KnowledgeProviderRegistry()
    registry.register(
        SupabaseKnowledgeProvider(session, vector_store=vector_store, embeddings=embeddings)
    )
    return registry
