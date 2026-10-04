"""Native general knowledge searches shared Graph facts and canonical sources."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.graph_v2 import GraphFact, GraphFactSource
from app.services.graph_v2.retrieval import hybrid_facts, neighbourhood
from app.services.knowledge.embeddings import require_embedding_vectors
from app.services.research.graph_grounding import (
    GraphResearchError,
    fact_is_current,
    grounded_fact_evidence,
)
from app.services.research.graph_reuse import GraphQueryEmbedding, _fact_context_allowed
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed, utc_now


async def shared_graph_has_evidence(session: AsyncSession) -> bool:
    present = await session.scalar(select(GraphFact.id).join(
        GraphFactSource, GraphFactSource.fact_id == GraphFact.id).where(
        GraphFact.scope_key == "shared", GraphFact.status == "active",
        GraphFactSource.source_kind == "text_unit").limit(1))
    return present is not None


async def _shared_candidates(session, *, need, embedding, limit):
    hits = await hybrid_facts(session, customer_id=None, query=need.question,
        embedding=embedding.vector, embedding_model=embedding.model, limit=limit)
    seeds = list(dict.fromkeys(node for hit in hits for node in (hit.fact.source_id, hit.fact.target_id)))
    expanded = await neighbourhood(session, customer_id=None, seeds=seeds,
        max_hops=1, limit=limit) if seeds else []
    unique = {}
    for hit in [*hits, *expanded]:
        unique.setdefault(hit.fact.id, hit)
    return list(unique.values())


async def lookup_shared_graph_evidence(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    context: ResearchContext,
    query_embedding: GraphQueryEmbedding | None,
    limit: int,
) -> list[ResearchEvidence]:
    if limit < 1:
        raise ValueError("Shared Graph retrieval limit must be positive")
    if not await shared_graph_has_evidence(session):
        return []
    if query_embedding is None:
        raise GraphResearchError("Prepare query embedding before opening the shared Graph read transaction")
    require_embedding_vectors([query_embedding.vector], dimension=query_embedding.dimension)
    hits = await _shared_candidates(session, need=need, embedding=query_embedding, limit=limit)
    now = utc_now()
    output, seen = [], set()
    for hit in hits:
        fact = hit.fact
        if fact.scope_key != "shared" or not fact_is_current(fact, now) or not _fact_context_allowed(fact, context):
            continue
        items = await grounded_fact_evidence(session, fact=fact, need=need, context=context,
            now=now, max_age_seconds=settings.research_knowledge_freshness_max_age_seconds)
        for item in items:
            ref = str(item.metadata["reuse"]["evidence_ref"])
            if ref not in seen and len(output) < limit:
                seen.add(ref)
                output.append(item)
        if len(output) == limit:
            break
    return output
