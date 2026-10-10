"""Workspace checks apply to graph reuse as well as direct document search."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.knowledge.document_grounding import readable_document_passage
from app.services.knowledge.shared_document_grounding import readable_shared_document_passage
from app.services.overgraph.research import knowledge_catalog, load_text_units
from app.services.research.models import ResearchContext, ResearchEvidence
from app.services.workspaces import company_workspace_id


def fact_workspace_allowed(fact, context: ResearchContext) -> bool:
    if fact.scope_key == "shared":
        return True
    workspace = fact.attributes.get("workspace_id") or company_workspace_id(
        context.scope.customer_id
    )
    allowed = context.scope.readable_workspace_ids or (
        company_workspace_id(context.scope.customer_id),
    )
    return workspace in allowed


def manifest_matches(fact, context: ResearchContext) -> bool:
    if context.scope.workspace_id is None:
        return fact.attributes.get("workspace_id") is None
    return fact.attributes.get("workspace_id") == context.scope.workspace_id and (
        fact.attributes.get("document_version_ids")
        == list(context.scope.allowed_document_version_ids or ())
    )


async def passages_allowed(session: AsyncSession, passages, context: ResearchContext) -> bool:
    for unit in passages:
        if unit.scope_key == "shared":
            if await readable_shared_document_passage(session, unit, allow_superseded=True) is None:
                return False
            continue
        document = await session.get(CanonicalDocumentRecord, unit.document_id)
        if document is not None and not document.source_object_id:
            if not await _unattached_passage_allowed(session, unit, document, context):
                return False
            continue
        if await readable_document_passage(session, unit, context.scope) is None:
            return False
    return True


async def basis_workspace_allowed(
    session: AsyncSession,
    basis: list[ResearchEvidence],
    context: ResearchContext,
) -> bool:
    for item in basis:
        metadata = item.metadata
        versions = set(metadata.get("document_version_ids") or ())
        if metadata.get("document_version_id"):
            versions.add(metadata["document_version_id"])
        for version_id in versions:
            version = await session.get(DocumentVersionRecord, version_id)
            if version is None:
                return False
            document = await session.get(CanonicalDocumentRecord, version.document_id)
            if document is None:
                return False
            ids = metadata.get("text_unit_ids") or metadata.get("supporting_text_unit_ids") or []
            if metadata.get("text_unit_id"):
                ids = [*ids, metadata["text_unit_id"]]
            if not ids:
                return False
            catalog = knowledge_catalog()
            units = await catalog.run(load_text_units, catalog, list(set(ids)))
            if any(unit is None or unit.document_version_id != version_id for unit in units):
                return False
            if not await passages_allowed(session, units, context):
                return False
    return True


async def _unattached_passage_allowed(session, unit, document, context) -> bool:
    if document.source_type == "uploaded_file":
        return False
    version = await session.get(DocumentVersionRecord, unit.document_version_id)
    if version is None or version.document_id != document.id:
        return False
    if any(row.customer_id != context.scope.customer_id for row in (unit, document, version)):
        return False
    workspace = document.extra.get("workspace_id") or company_workspace_id(
        context.scope.customer_id
    )
    allowed = context.scope.readable_workspace_ids or (
        company_workspace_id(context.scope.customer_id),
    )
    return workspace in allowed
