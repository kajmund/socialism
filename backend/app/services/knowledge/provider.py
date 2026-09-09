"""Read-only KnowledgeProvider contract. No upload/delete/overwrite."""

from __future__ import annotations

from typing import Protocol

from app.services.knowledge.models import (
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
)

SUPABASE_PROVIDER_ID = "supabase"


class KnowledgeError(Exception):
    """Base error for the knowledge layer."""


class KnowledgeNotFoundError(KnowledgeError):
    """Document does not exist or is not visible in the requested scope."""


class KnowledgeProviderNotFoundError(KnowledgeError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(f"Unknown knowledge provider: {provider_id}")
        self.provider_id = provider_id


class KnowledgeVectorStoreError(KnowledgeError):
    """Vector store adapter failed. Not a cue to try another backend."""


class KnowledgeProvider(Protocol):
    """Research-facing read API. Writes stay on existing file-storage flows."""

    provider_id: str

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]: ...

    async def get_document(
        self,
        document_id: str,
        scope: KnowledgeScope,
    ) -> KnowledgeDocument | None: ...

    async def fetch_content(self, document_id: str, scope: KnowledgeScope) -> bytes: ...
