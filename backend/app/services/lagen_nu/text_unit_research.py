"""Research reads lagen.nu through ingested TextUnits.

MCP may fetch a document that is not yet ingested. After that, the
interpreter corpus is the current TextUnits — not MCP text or RawSource.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.persistence import (
    get_canonical_document_by_identity,
    get_current_document_version,
)
from app.services.knowledge.units import TextUnit
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import (
    ingest_lagen_nu_document,
    lagen_nu_source_identity,
)
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.registration import LAGEN_NU_PROVIDER_ID
from app.services.lagen_nu.uris import canonical_lagen_nu_document_uri
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.owner_writer import load_text_units_via_owner
from app.services.overgraph.text_units import load_domain_text_units


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


async def current_lagen_nu_units(
    session: AsyncSession,
    *,
    customer_id: int,
    canonical_uri: str,
) -> list[TextUnit] | None:
    row = await get_canonical_document_by_identity(
        session,
        customer_id=customer_id,
        source_type=LAGEN_NU_PROVIDER_ID,
        canonical_uri=canonical_uri,
    )
    if row is None:
        return None
    version = await get_current_document_version(session, row.id)
    if version is None:
        raise LagenNuResearchKnowledgeError(
            f"CanonicalDocument {row.id} has no current version"
        )
    owner = get_owner_runtime().client
    if owner is not None:
        units = await load_text_units_via_owner(
            owner, document_version_id=version.id,
        )
    else:
        units = await asyncio.to_thread(
            load_domain_text_units, require_knowledge(), document_version_id=version.id,
        )
    if not units:
        # SQL metadata can survive an OverGraph reset; treat this as "not
        # ingested" so the provider fetches and re-materialises TextUnits.
        return None
    return units


async def ingest_and_load_text_units(
    session: AsyncSession,
    *,
    customer_id: int,
    document: LagenNuDocument,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
) -> tuple[KnowledgeIngestResult, list[TextUnit] | None]:
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
