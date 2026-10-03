"""SQL authority for private document discovery and original source passages."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    CanonicalDocumentRecord,
    DocumentKnowledgeItem,
    DocumentVersionRecord,
    StoredObject,
    TextUnitRecord,
)
from app.services.knowledge.models import KnowledgeHit, KnowledgeScope, KnowledgeScopeRequiredError
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
    item_id = hit.metadata.get("document_knowledge_item_id")
    if isinstance(item_id, str):
        return await _item_hits(session, hit, scope, item_id)
    unit_id = hit.metadata.get("text_unit_id")
    if not isinstance(unit_id, str):
        return []
    unit = await session.get(TextUnitRecord, unit_id)
    if unit is None or unit.document_id != hit.document_id:
        return []
    version_id = hit.metadata.get("document_version_id")
    if version_id != unit.document_version_id:
        return []
    basis = await readable_document_passage(session, unit, scope)
    return [_passage(hit, unit, basis)] if basis else []


async def _item_hits(
    session: AsyncSession,
    hit: KnowledgeHit,
    scope: KnowledgeScope,
    item_id: str,
) -> list[KnowledgeHit]:
    item = await session.scalar(
        select(DocumentKnowledgeItem)
        .options(
            selectinload(DocumentKnowledgeItem.anchors),
            selectinload(DocumentKnowledgeItem.text_unit_links),
        )
        .where(DocumentKnowledgeItem.id == item_id)
    )
    if item is None or item.status != "active" or item.customer_id != scope.customer_id:
        return []
    if hit.metadata.get("item_revision") != item.revision:
        return []
    units = await _item_units(session, hit, item)
    if units is None:
        return []
    out = []
    for unit in units:
        basis = await readable_document_passage(session, unit, scope)
        if basis is None or basis[0].source_object_id != item.source_object_id:
            return []
        passage = _passage(hit, unit, basis)
        metadata = {
            **passage.metadata,
            "discovery_kind": "document_item",
            "document_knowledge_item_id": item.id,
            "item_revision": item.revision,
            "qa_snapshot": {
                "kind": item.kind,
                "question": item.question,
                "content": item.content,
                "anchors": [{"locator": anchor.locator, "exact_text": anchor.exact_text} for anchor in item.anchors],
            },
        }
        out.append(replace(passage, metadata=metadata))
    return out


async def _item_units(session: AsyncSession, hit: KnowledgeHit, item: DocumentKnowledgeItem) -> list[TextUnitRecord] | None:
    ids = [link.text_unit_id for link in item.text_unit_links]
    if not ids:
        return None
    units = list(await session.scalars(select(TextUnitRecord).where(TextUnitRecord.id.in_(ids))))
    if len(units) != len(ids) or len({unit.document_version_id for unit in units}) != 1:
        return None
    if hit.metadata.get("document_version_id") != units[0].document_version_id:
        return None
    supplied = hit.metadata.get("text_unit_ids")
    if not isinstance(supplied, list) or not all(isinstance(value, str) for value in supplied) or set(supplied) != set(ids):
        return None
    if not _anchors_grounded(item, units):
        return None
    return units


def _anchors_grounded(item: DocumentKnowledgeItem, units: list[TextUnitRecord]) -> bool:
    if not item.anchors:
        return False
    return all(
        anchor.exact_text and any(
            _normalized(anchor.exact_text) in _normalized(unit.text)
            and (anchor.locator is None or anchor.locator == unit.locator)
            for unit in units
        )
        for anchor in item.anchors
    )


async def readable_document_passage(
    session: AsyncSession,
    unit: TextUnitRecord,
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
    unit: TextUnitRecord,
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


def _normalized(text: str) -> str:
    return " ".join(text.split())
