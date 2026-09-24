"""Map a lagen.nu document onto the shared TextUnit ingest pipeline.

This adapter owns lagen.nu identity. The knowledge core stays domain-neutral.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.extractors import DefaultTextExtractor, PLAIN_TEXT_MIME, TextExtractor
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.registration import LAGEN_NU_PROVIDER_ID
from app.services.lagen_nu.uris import canonical_lagen_nu_document_uri


def lagen_nu_canonical_document_id(*, customer_id: int, canonical_uri: str) -> str:
    payload = f"{customer_id}\0{LAGEN_NU_PROVIDER_ID}\0{canonical_uri}".encode()
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
    customer_id: int,
    document: LagenNuDocument,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
    extractor: TextExtractor | None = None,
    case_id: str | None = None,
    module: str | None = None,
) -> KnowledgeIngestResult:
    """Segment and persist a fetched lagen.nu document as TextUnits."""
    canonical_uri = lagen_nu_source_identity(document)
    document_id = lagen_nu_canonical_document_id(
        customer_id=customer_id,
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
        scope=KnowledgeScope(customer_id=customer_id, case_id=case_id, module=module),
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
        customer_id=customer_id,
        extracted=extracted,
        document=knowledge_document,
        source_type=LAGEN_NU_PROVIDER_ID,
        canonical_uri=canonical_uri,
        content_hash=hash_text(document.text),
        embeddings=embeddings,
        vector_store=vector_store,
    )
