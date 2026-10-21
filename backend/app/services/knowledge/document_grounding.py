"""SQL authority for private document discovery and original source passages."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    StoredObject,
)
from app.services.knowledge.models import KnowledgeHit, KnowledgeScope, KnowledgeScopeRequiredError
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.model import TextUnitView
from app.services.overgraph.research import load_text_units
from app.services.workspaces import company_workspace_id


def source_visible(source: StoredObject, scope: KnowledgeScope) -> bool:
    if source.customer_id != scope.customer_id:
        return False
    if scope.workspace_id is None and scope.module is not None and source.module != scope.module:
        return False
    if scope.workspace_id is not None:
        allowed = scope.readable_workspace_ids or (scope.workspace_id,)
        if source.workspace_id not in allowed:
            return False
    else:
        if source.workspace_id != company_workspace_id(scope.customer_id):
            return False
        if scope.case_id is not None and source.id != scope.case_id:
            return False
    selected = scope.allowed_source_object_ids
    return selected is None or source.id in selected


async def validate_manifest(session: AsyncSession, scope: KnowledgeScope) -> None:
    """An explicit selection is an access constraint, never a vector suggestion."""
    if scope.allowed_source_object_ids is not None:
        for object_id in scope.allowed_source_object_ids:
            source = await session.get(StoredObject, object_id)
            if source is None or not source_visible(source, scope):
                raise KnowledgeScopeRequiredError("Selected document is outside research scope")
    if scope.allowed_document_version_ids is not None:
        for version_id in scope.allowed_document_version_ids:
            version = await session.get(DocumentVersionRecord, version_id)
            document = await session.get(CanonicalDocumentRecord, version.document_id) if version else None
            source = await session.get(StoredObject, document.source_object_id) if document else None
            if source is None or not source_visible(source, scope):
                raise KnowledgeScopeRequiredError("Selected document version is outside research scope")
            if version.customer_id != scope.customer_id:
                raise KnowledgeScopeRequiredError("Selected document version is outside research scope")
            if version.superseded_at is not None:
                raise KnowledgeScopeRequiredError("Selected document version has been superseded")


async def grounded_hits(
    session: AsyncSession,
    hit: KnowledgeHit,
    scope: KnowledgeScope,
) -> list[KnowledgeHit]:
    unit_id = hit.metadata.get("text_unit_id")
    if not isinstance(unit_id, str):
        return []
    catalog = require_knowledge()
    units = await catalog.run(load_text_units, catalog, [unit_id])
    unit = units[0] if units else None
    if unit is None or unit.document_id != hit.document_id:
        return []
    version_id = hit.metadata.get("document_version_id")
    if version_id != unit.document_version_id:
        return []
    basis = await readable_document_passage(session, unit, scope)
    return [_passage(hit, unit, basis)] if basis else []


async def readable_document_passage(
    session: AsyncSession,
    unit: TextUnitView,
    scope: KnowledgeScope,
) -> tuple[CanonicalDocumentRecord, DocumentVersionRecord, StoredObject] | None:
    """Return SQL provenance only for a private passage inside the reader manifest."""
    document = await session.get(CanonicalDocumentRecord, unit.document_id)
    version = await session.get(DocumentVersionRecord, unit.document_version_id)
    if document is None or version is None or version.document_id != document.id:
        return None
    if any(row.customer_id != scope.customer_id for row in (unit, document, version)):
        return None
    selected = scope.allowed_document_version_ids
    if selected is not None:
        if version.id not in selected:
            return None
    elif version.superseded_at is not None:
        return None
    source = await session.get(StoredObject, document.source_object_id)
    if source is None or not source_visible(source, scope):
        return None
    return document, version, source


def _passage(
    hit: KnowledgeHit,
    unit: TextUnitView,
    basis: tuple[CanonicalDocumentRecord, DocumentVersionRecord, StoredObject],
) -> KnowledgeHit:
    document, version, source = basis
    return KnowledgeHit(
        document_id=document.id,
        provider=hit.provider,
        title=source.filename,
        excerpt=unit.text,
        score=hit.score,
        locator=unit.locator,
        external_id=document.canonical_uri,
        metadata={
            "knowledge_kind": "document_chunk",
            "document_id": document.id,
            "document_version_id": version.id,
            "source_object_id": source.id,
            "workspace_id": source.workspace_id,
            "customer_id": source.customer_id,
            "scope_type": "customer",
            "scope_key": f"customer:{source.customer_id}",
            "text_unit_id": unit.id,
            "text_unit_ids": [unit.id],
            "content_hash": unit.content_hash,
            "version_content_hash": version.content_hash,
            "version": version.version,
            "page_start": unit.page_start,
            "page_end": unit.page_end,
            "source_url": f"/underlag/{source.id}/file",
        },
    )
