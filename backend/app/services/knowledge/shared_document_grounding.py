"""Shared source passages stay global regardless of the researching organisation."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, TextUnitRecord
from app.services.knowledge.models import KnowledgeHit


async def grounded_shared_hits(session: AsyncSession, hit: KnowledgeHit) -> list[KnowledgeHit]:
    unit_id = hit.metadata.get("text_unit_id")
    if not isinstance(unit_id, str):
        return []
    unit = await session.get(TextUnitRecord, unit_id)
    if unit is None or unit.document_id != hit.document_id:
        return []
    basis = await readable_shared_document_passage(session, unit)
    if basis is None:
        return []
    document, version = basis
    if (
        hit.metadata.get("document_version_id") != version.id
        or (document.extra or {}).get("provider") != hit.provider
    ):
        return []
    return [KnowledgeHit(
        document_id=document.id, provider=hit.provider, title=document.title,
        excerpt=unit.text, score=hit.score, locator=unit.locator, external_id=document.canonical_uri,
        metadata={
            "knowledge_kind": "document_chunk", "document_id": document.id,
            "document_version_id": version.id, "text_unit_id": unit.id,
            "text_unit_ids": [unit.id], "scope_type": "shared", "scope_key": "shared",
            "customer_id": None, "workspace_id": None, "content_hash": unit.content_hash,
            "version_content_hash": version.content_hash,
            "version": version.version,
            "source_url": document.canonical_uri if document.canonical_uri.startswith(("https://", "http://")) else None,
        },
    )]


async def readable_shared_document_passage(
    session: AsyncSession,
    unit: TextUnitRecord,
    *,
    allow_superseded: bool = False,
) -> tuple[CanonicalDocumentRecord, DocumentVersionRecord] | None:
    """SQL provenance must be global throughout and never reference a private file."""
    document = await session.get(CanonicalDocumentRecord, unit.document_id)
    version = await session.get(DocumentVersionRecord, unit.document_version_id)
    if document is None or version is None or version.document_id != document.id:
        return None
    if (
        any(row.scope_type != "shared" or row.scope_key != "shared" or row.customer_id is not None
            for row in (unit, document, version))
        or document.source_object_id is not None
        or (version.superseded_at is not None and not allow_superseded)
    ):
        return None
    return document, version
