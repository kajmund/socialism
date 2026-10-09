"""Materialize source access before any embedding, vector or object-storage call."""

import asyncio
from dataclasses import dataclass
from io import BytesIO

import pdfplumber
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceSource
from app.services.document_knowledge import (
    _normalized, _page_number, _quote_rects,
)
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider, require_embedding_vectors
from app.services.knowledge.models import EmbeddedKnowledgeQuery, KnowledgeHit, KnowledgeQuery, KnowledgeScope
from app.services.knowledge.document_grounding import grounded_hits
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID
from app.services.object_storage import get_object
from app.services.research.composition import require_knowledge_vector_store
from app.services.research.graph_reuse import GraphQueryEmbedding
from app.services.research.models import RESEARCH_SOURCE_TYPES, ResearchContext, ResearchNeed
from app.services.document_navigation import metadata_in_worker_sections
from app.services.workspace.service import require_source, require_workspace
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
        pdf_bytes = None
        scoped = KnowledgeQuery(query=query.query, limit=query.limit * 8, filters={"source_object_id": source.id},
            scope=KnowledgeScope(customer_id=query.scope.customer_id, case_id=source.id, module=source.module,
                workspace_id=query.scope.workspace_id, readable_workspace_ids=query.scope.readable_workspace_ids,
                allowed_source_object_ids=(source.id,), allowed_document_version_ids=source.document_version_ids))
        hits = await store.search(EmbeddedKnowledgeQuery(query=scoped, embedding=vectors[0]))
        if hits and source.content_type == "application/pdf":
            pdf_bytes, _mime = await get_object(source.bucket, source.key)
        for hit in hits:
            output.append((source, hit, pdf_bytes))
    output.sort(key=lambda value: value[1].score or 0, reverse=True)
    return output


async def _hit_reference(session: AsyncSession, workspace: VoiceWorkspace, found: tuple):
    source_input, hit, pdf_bytes = found
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
    passage, quote = _citation_passage(passages)
    if not quote or _normalized(quote) not in _normalized(source.extracted_text or ""):
        raise HTTPException(status_code=409, detail="source_excerpt_stale")
    page = _page_number(passage.locator or "")
    rects = await asyncio.to_thread(_pdf_quote_rects, pdf_bytes, page, quote) if pdf_bytes is not None and page else []
    anchor = {"anchor_type": "text", "page_number": page,
              "locator": passage.locator, "exact_text": quote, "rects": rects}
    snapshot = {"title": passage.title or source.filename, "excerpt": quote,
                "kind": "document_chunk", **passage.metadata}
    return await citation(session, workspace, kind="underlag", source_id=source.id,
                          version=source_input.version, anchor=anchor, snapshot=snapshot)


def _citation_passage(passages: list[KnowledgeHit]) -> tuple[KnowledgeHit, str]:
    for passage in passages:
        qa = passage.metadata.get("qa_snapshot")
        if qa is None:
            return passage, passage.excerpt
        for anchor in qa["anchors"]:
            quote = anchor["exact_text"]
            if anchor["locator"] in (None, passage.locator) and _normalized(quote) in _normalized(passage.excerpt):
                return passage, quote
    raise HTTPException(status_code=409, detail="source_excerpt_stale")


async def _fresh_workspace(session: AsyncSession, workspace_id: str, actor_id: str) -> VoiceWorkspace:
    actor = await session.get(UserAccount, actor_id, populate_existing=True)
    if actor is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    await session.get(VoiceWorkspace, workspace_id, populate_existing=True)
    return await require_workspace(session, workspace_id, actor)


async def search_workspace(
    session: AsyncSession, workspace: VoiceWorkspace, query: str, limit: int, *, source_id: str | None = None,
) -> dict:
    workspace_id, actor_id = workspace.id, workspace.owner_user_id
    members = list((await session.scalars(select(WorkspaceSource).where(WorkspaceSource.workspace_id == workspace.id))).all())
    if source_id is not None and source_id not in {member.source_id for member in members}:
        raise HTTPException(status_code=404, detail="workspace_source_not_found")
    members = [member for member in members if source_id is None or member.source_id == source_id]
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
    workspace = await _fresh_workspace(session, workspace_id, actor_id)
    refs = []
    for value in found:
        if not metadata_in_worker_sections(value[1].metadata):
            continue
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
    workspace_id, actor_id = workspace.id, workspace.owner_user_id
    present = await shared_graph_has_evidence(session)
    scope = KnowledgeScope(customer_id=workspace.customer_id, module=workspace.module)
    await session.commit()
    embedding = await _query_embedding(query) if present else None
    workspace = await _fresh_workspace(session, workspace_id, actor_id)
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
