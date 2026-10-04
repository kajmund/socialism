"""Materialize source access before any embedding, vector or object-storage call."""

import asyncio
from dataclasses import dataclass
from io import BytesIO

import pdfplumber
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, StoredObject
from app.database.workspace_models import VoiceWorkspace, WorkspaceSource
from app.services.document_knowledge import (
    _normalized, _page_number, _quote_rects,
)
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider, require_embedding_vectors
from app.services.knowledge.models import EmbeddedKnowledgeQuery, KnowledgeQuery, KnowledgeScope
from app.services.knowledge.document_grounding import grounded_hits
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID
from app.services.object_storage import get_object
from app.services.research.composition import require_knowledge_vector_store
from app.services.research.graph_reuse import GraphQueryEmbedding
from app.services.research.models import RESEARCH_SOURCE_TYPES, ResearchContext, ResearchNeed
from app.services.workspace.service import require_source
from app.services.workspace.shared_graph import lookup_shared_graph_evidence, shared_graph_has_evidence
from app.services.workspace.sources import citation, reference_out, source_version
from app.services.workspaces import resolve_readable_workspace_ids


@dataclass(frozen=True)
class SourceInput:
    id: str
    module: str
    version: str
    text: str
    filename: str
    content_type: str
    bucket: str
    key: str
    document_version_ids: tuple[str, ...]


async def _materialize(session: AsyncSession, source: StoredObject) -> SourceInput:
    versions = await session.scalars(select(DocumentVersionRecord.id).join(
        CanonicalDocumentRecord, CanonicalDocumentRecord.id == DocumentVersionRecord.document_id).where(
        CanonicalDocumentRecord.source_object_id == source.id, DocumentVersionRecord.superseded_at.is_(None)))
    return SourceInput(source.id, source.module, source_version(source), source.extracted_text, source.filename,
                       source.content_type, source.bucket, source.object_key, tuple(versions))


def _pdf_quote_rects(data: bytes, page: int, quote: str) -> list[dict]:
    with pdfplumber.open(BytesIO(data)) as pdf:
        return _quote_rects(pdf, page, quote)


async def _external_search(sources: list[SourceInput], query: KnowledgeQuery) -> list[tuple]:
    embeddings = OpenAIEmbeddingProvider.from_settings()
    vectors = require_embedding_vectors(await embeddings.embed([query.query]), dimension=embeddings.dimension)
    if len(vectors) != 1:
        raise RuntimeError("Embedding provider must return one query vector")
    store = require_knowledge_vector_store()
    output = []
    for source in sources:
        scoped = KnowledgeQuery(query=query.query, limit=query.limit * 8,
            scope=KnowledgeScope(customer_id=query.scope.customer_id, case_id=source.id, module=source.module,
                workspace_id=query.scope.workspace_id, readable_workspace_ids=query.scope.readable_workspace_ids,
                allowed_source_object_ids=(source.id,), allowed_document_version_ids=source.document_version_ids))
        hits = await store.search(EmbeddedKnowledgeQuery(query=scoped, embedding=vectors[0]))
        for hit in hits:
            rects = []
            page = _page_number(hit.locator or "")
            if source.content_type == "application/pdf" and page:
                data, _mime = await get_object(source.bucket, source.key)
                rects = await asyncio.to_thread(_pdf_quote_rects, data, page, hit.excerpt)
            output.append((source, hit, rects))
    output.sort(key=lambda value: value[1].score or 0, reverse=True)
    return output


async def _hit_reference(session: AsyncSession, workspace: VoiceWorkspace, found: tuple):
    source_input, hit, rects = found
    source = await require_source(session, workspace, source_input.id)
    if source_version(source) != source_input.version:
        raise HTTPException(status_code=409, detail="workspace_source_changed_during_search")
    if hit.provider != SUPABASE_PROVIDER_ID:
        return None
    readable = await resolve_readable_workspace_ids(session, customer_id=workspace.customer_id,
        user_id=workspace.owner_user_id, workspace_id=workspace.workspace_id)
    scope = KnowledgeScope(customer_id=workspace.customer_id, module=source.module,
        workspace_id=workspace.workspace_id, readable_workspace_ids=tuple(readable),
        allowed_source_object_ids=(source.id,), allowed_document_version_ids=source_input.document_version_ids)
    passages = await grounded_hits(session, hit, scope)
    if not passages:
        return None
    passage = passages[0]
    if not passage.excerpt or _normalized(passage.excerpt) not in _normalized(source.extracted_text or ""):
        raise HTTPException(status_code=409, detail="source_excerpt_stale")
    anchor = {"anchor_type": "text", "page_number": _page_number(passage.locator or ""),
              "locator": passage.locator, "exact_text": passage.excerpt, "rects": rects}
    snapshot = {"title": passage.title or source.filename, "excerpt": passage.excerpt,
                "kind": "document_chunk", **passage.metadata}
    return await citation(session, workspace, kind="underlag", source_id=source.id,
                          version=source_input.version, anchor=anchor, snapshot=snapshot)


async def search_workspace(session: AsyncSession, workspace: VoiceWorkspace, query: str, limit: int) -> dict:
    members = list((await session.scalars(select(WorkspaceSource).where(WorkspaceSource.workspace_id == workspace.id))).all())
    sources = [await require_source(session, workspace, member.source_id) for member in members]
    readable = [await _materialize(session, source) for source in sources if source.knowledge_status in {"ready", "partial"} and source.extracted_text]
    gaps = [{"source_id": source.id, "status": source.knowledge_status, "detail": source.knowledge_error}
            for source in sources if source.knowledge_status != "ready"]
    if not readable:
        return {"items": [], "gaps": gaps}
    parent_ids = await resolve_readable_workspace_ids(session, customer_id=workspace.customer_id,
        user_id=workspace.owner_user_id, workspace_id=workspace.workspace_id)
    scoped = KnowledgeQuery(query=query, limit=limit, scope=KnowledgeScope(customer_id=workspace.customer_id,
        module=workspace.module, workspace_id=workspace.workspace_id, readable_workspace_ids=tuple(parent_ids)))
    await session.commit()
    found = await _external_search(readable, scoped)
    refs = []
    for value in found:
        ref = await _hit_reference(session, workspace, value)
        if ref is not None and ref.id not in {existing.id for existing in refs}:
            refs.append(ref)
        if len(refs) >= limit:
            break
    return {"items": [reference_out(ref) for ref in refs], "gaps": gaps}


async def _query_embedding(query: str) -> GraphQueryEmbedding:
    embeddings = OpenAIEmbeddingProvider.from_settings()
    vectors = require_embedding_vectors(await embeddings.embed([query]), dimension=embeddings.dimension)
    if len(vectors) != 1:
        raise RuntimeError("Embedding provider must return one query vector")
    return GraphQueryEmbedding(embeddings.model, embeddings.dimension, vectors[0])


async def search_general(session: AsyncSession, workspace: VoiceWorkspace, query: str, limit: int) -> dict:
    present = await shared_graph_has_evidence(session)
    scope = KnowledgeScope(customer_id=workspace.customer_id, module=workspace.module)
    await session.commit()
    embedding = await _query_embedding(query) if present else None
    candidates = await lookup_shared_graph_evidence(session,
        need=ResearchNeed(id="workspace_search", question=query, why_needed="", source_types=list(RESEARCH_SOURCE_TYPES)),
        context=ResearchContext(scope=scope), query_embedding=embedding, limit=limit)
    refs = []
    for item in candidates:
        version = await session.get(DocumentVersionRecord, item.metadata["document_version_id"])
        if version is None:
            raise HTTPException(status_code=409, detail="workspace_graph_grounding_invalid")
        ref = await citation(session, workspace, kind="graph", source_id=version.id, version=version.content_hash,
            anchor={"anchor_type": "text", "locator": item.locator, "exact_text": item.excerpt, "rects": []},
            snapshot={"title": item.title, "excerpt": item.excerpt, "source_url": item.source_url,
                      "source_type": item.source_type, **item.metadata})
        refs.append(ref)
    return {"items": [reference_out(ref) for ref in refs], "gaps": [] if refs else [{"status": "not_found"}]}
