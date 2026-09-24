"""Map a lagen.nu document onto the shared TextUnit ingest pipeline.

This adapter owns lagen.nu identity. The knowledge core stays domain-neutral.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.extractors import PLAIN_TEXT_MIME, DefaultTextExtractor, TextExtractor
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeTenantScope,
    require_persist_scope,
)
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.registration import LAGEN_NU_PROVIDER_ID
from app.services.lagen_nu.uris import canonical_lagen_nu_document_uri


def lagen_nu_canonical_document_id(
    *,
    canonical_uri: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
) -> str:
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    if resolved.scope_type == SCOPE_CUSTOMER:
        payload = f"{resolved.customer_id}\0{LAGEN_NU_PROVIDER_ID}\0{canonical_uri}".encode()
    else:
        payload = f"shared\0{LAGEN_NU_PROVIDER_ID}\0{canonical_uri}".encode()
    return hashlib.sha256(payload).hexdigest()


def lagen_nu_source_identity(document: LagenNuDocument) -> str:
    uri = canonical_lagen_nu_document_uri(document.uri)
    if uri is None:
        raise ValueError(
            f"lagen.nu document URI is not a canonical lagen.nu URI: {document.uri!r}"
        )
    return uri


async def ingest_lagen_nu_document(
    session: AsyncSession,
    *,
    document: LagenNuDocument,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
    extractor: TextExtractor | None = None,
    case_id: str | None = None,
    module: str | None = None,
) -> KnowledgeIngestResult:
    """Segment and persist a fetched lagen.nu document as TextUnits."""
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    canonical_uri = lagen_nu_source_identity(document)
    document_id = lagen_nu_canonical_document_id(
        scope=resolved,
        canonical_uri=canonical_uri,
    )
    extracted = await (extractor or DefaultTextExtractor()).extract(
        document.text.encode("utf-8"),
        PLAIN_TEXT_MIME,
    )
    knowledge_document = KnowledgeDocument(
        document_id=document_id,
        provider=LAGEN_NU_PROVIDER_ID,
        external_id=canonical_uri,
        title=document.title or canonical_uri,
        mime_type=PLAIN_TEXT_MIME,
        scope=KnowledgeScope(
            customer_id=resolved.customer_id,
            case_id=case_id,
            module=module,
            scope_type=resolved.scope_type,
        ),
        source_type=LAGEN_NU_PROVIDER_ID,
        canonical_uri=canonical_uri,
        metadata={
            "kind": document.kind,
            "source": document.source,
            "publisher_source_url": document.publisher_source_url,
            "truncated": document.truncated,
        },
    )
    return await ingest_extracted_source(
        session,
        scope=resolved,
        extracted=extracted,
        document=knowledge_document,
        source_type=LAGEN_NU_PROVIDER_ID,
        canonical_uri=canonical_uri,
        content_hash=hash_text(document.text),
        embeddings=embeddings,
        vector_store=vector_store,
    )
