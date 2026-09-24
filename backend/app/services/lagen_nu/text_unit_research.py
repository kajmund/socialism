"""Research reads lagen.nu through ingested TextUnits.

MCP may fetch a document that is not yet ingested. After that, the
interpreter corpus is the current TextUnits — not MCP text or RawSource.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TextUnitRecord
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.persistence import (
    current_text_units,
    get_canonical_document_by_identity,
)
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import (
    ingest_lagen_nu_document,
    lagen_nu_source_identity,
)
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.registration import LAGEN_NU_PROVIDER_ID
from app.services.lagen_nu.uris import canonical_lagen_nu_document_uri


class LagenNuResearchKnowledgeError(RuntimeError):
    """lagen.nu research cannot run without the TextUnit ingest path."""


def require_lagen_nu_research_knowledge(
    *,
    session: AsyncSession | None,
    embeddings: EmbeddingProvider | None,
    vector_store: KnowledgeVectorStore | None,
) -> tuple[AsyncSession, EmbeddingProvider, KnowledgeVectorStore]:
    if session is None or embeddings is None or vector_store is None:
        raise LagenNuResearchKnowledgeError(
            "lagen.nu research requires session, embeddings, and vector_store; "
            "refusing to interpret raw MCP text"
        )
    return session, embeddings, vector_store


def document_identity_uri(uri: str) -> str:
    identity = canonical_lagen_nu_document_uri(uri)
    if identity is None:
        raise LagenNuResearchKnowledgeError(
            f"lagen.nu research URI is not a canonical lagen.nu document: {uri!r}"
        )
    return identity


def join_text_units(units: list[TextUnitRecord]) -> str:
    return "\n\n".join(unit.text for unit in units)


async def current_lagen_nu_units(
    session: AsyncSession,
    *,
    customer_id: int,
    canonical_uri: str,
) -> list[TextUnitRecord] | None:
    row = await get_canonical_document_by_identity(
        session,
        customer_id=customer_id,
        source_type=LAGEN_NU_PROVIDER_ID,
        canonical_uri=canonical_uri,
    )
    if row is None:
        return None
    units = await current_text_units(session, row.id)
    if not units:
        raise LagenNuResearchKnowledgeError(
            f"CanonicalDocument {row.id} has no current TextUnits"
        )
    return units


async def ingest_and_load_text_units(
    session: AsyncSession,
    *,
    customer_id: int,
    document: LagenNuDocument,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
) -> tuple[KnowledgeIngestResult, list[TextUnitRecord] | None]:
    result = await ingest_lagen_nu_document(
        session,
        customer_id=customer_id,
        document=document,
        embeddings=embeddings,
        vector_store=vector_store,
    )
    if result.status != "indexed":
        return result, None
    units = await current_lagen_nu_units(
        session,
        customer_id=customer_id,
        canonical_uri=lagen_nu_source_identity(document),
    )
    return result, units
