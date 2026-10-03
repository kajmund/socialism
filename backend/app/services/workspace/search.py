"""Materialize source access before any embedding, vector or object-storage call."""

import asyncio
from dataclasses import dataclass
from io import BytesIO

import pdfplumber
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact, GraphFactSource
from app.database.models import DocumentVersionRecord, KnowledgeDocumentRecord, StoredObject
from app.database.workspace_models import Workspace, WorkspaceSource
from app.services.document_knowledge import (
    _normalized, _page_number, _quote_rects, list_document_knowledge, serialize_document_knowledge_item,
)
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider, require_embedding_vectors
from app.services.knowledge.models import EmbeddedKnowledgeQuery, KnowledgeQuery, KnowledgeScope
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID
from app.services.object_storage import get_object
from app.services.research.composition import require_knowledge_vector_store
from app.services.research.graph_reuse import GraphQueryEmbedding, lookup_graph_evidence
from app.services.research.models import RESEARCH_SOURCE_TYPES, ResearchContext, ResearchNeed
from app.services.workspace.service import require_source
from app.services.workspace.sources import citation, reference_out, source_version


@dataclass(frozen=True)
class SourceInput:
    id: str
    version: str
    text: str
    filename: str
    content_type: str
    bucket: str
    key: str


def _materialize(source: StoredObject) -> SourceInput:
    return SourceInput(source.id, source_version(source), source.extracted_text, source.filename,
                       source.content_type, source.bucket, source.object_key)


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
            scope=KnowledgeScope(customer_id=query.scope.customer_id, case_id=source.id, module=query.scope.module))
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


async def _hit_reference(session: AsyncSession, workspace: Workspace, found: tuple):
    source_input, hit, rects = found
    source = await require_source(session, workspace, source_input.id)
    if source_version(source) != source_input.version:
        raise HTTPException(status_code=409, detail="workspace_source_changed_during_search")
    indexed = await session.get(KnowledgeDocumentRecord, hit.document_id)
    if (hit.provider != SUPABASE_PROVIDER_ID or indexed is None or indexed.provider != SUPABASE_PROVIDER_ID
            or indexed.customer_id != workspace.customer_id or indexed.case_id != source.id
            or indexed.module != workspace.module or indexed.source_object_id != source.id):
        return None
    items = await list_document_knowledge(session, source_object_id=source.id)
    item_id = hit.metadata.get("document_knowledge_item_id")
    item = next((row for row in items if row.id == item_id and row.status == "active"), None)
    if item_id and item is None:
        raise HTTPException(status_code=409, detail="knowledge_item_stale")
    if item is not None:
        value = serialize_document_knowledge_item(item)
        anchor = value["anchors"][0] if value["anchors"] else {}
        snapshot = {"title": item.title, "excerpt": item.content, "item_id": item.id, "item_revision": item.revision}
    else:
        if not hit.excerpt or _normalized(hit.excerpt) not in _normalized(source.extracted_text or ""):
            raise HTTPException(status_code=409, detail="source_excerpt_stale")
        anchor = {"anchor_type": "text", "page_number": _page_number(hit.locator or ""),
                  "locator": hit.locator, "exact_text": hit.excerpt, "rects": rects}
        snapshot = {"title": hit.title or source.filename, "excerpt": hit.excerpt, "kind": "document_chunk"}
    return await citation(session, workspace, kind="underlag", source_id=source.id,
                          version=source_input.version, anchor=anchor, snapshot=snapshot)


async def search_workspace(session: AsyncSession, workspace: Workspace, query: str, limit: int) -> dict:
    members = list((await session.scalars(select(WorkspaceSource).where(WorkspaceSource.workspace_id == workspace.id))).all())
    sources = [await require_source(session, workspace, member.source_id) for member in members]
    readable = [_materialize(source) for source in sources if source.knowledge_status in {"ready", "partial"} and source.extracted_text]
    gaps = [{"source_id": source.id, "status": source.knowledge_status, "detail": source.knowledge_error}
            for source in sources if source.knowledge_status != "ready"]
    if not readable:
        return {"items": [], "gaps": gaps}
    scoped = KnowledgeQuery(query=query, limit=limit, scope=KnowledgeScope(customer_id=workspace.customer_id, module=workspace.module))
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


async def search_general(session: AsyncSession, workspace: Workspace, query: str, limit: int) -> dict:
    present = await session.scalar(select(GraphFact.id).join(GraphFactSource, GraphFactSource.fact_id == GraphFact.id).where(
        GraphFact.scope_key.in_(("shared", f"customer:{workspace.customer_id}")),
        GraphFact.status == "active", GraphFactSource.source_kind == "text_unit").limit(1))
    customer_id = workspace.customer_id
    await session.commit()
    embedding = await _query_embedding(query) if present is not None else None
    candidates = await lookup_graph_evidence(session,
        need=ResearchNeed(id="workspace_search", question=query, why_needed="", source_types=list(RESEARCH_SOURCE_TYPES)),
        context=ResearchContext(scope=KnowledgeScope(customer_id=customer_id)), query_embedding=embedding, limit=limit)
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
