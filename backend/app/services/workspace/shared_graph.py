"""Native general knowledge searches shared Graph facts and canonical sources."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.knowledge.embeddings import require_embedding_vectors
from app.services.overgraph.research import graph_has_supported_facts, lookup_candidates
from app.services.research.graph_grounding import (
    GraphResearchError,
    fact_is_current,
    grounded_fact_evidence,
)
from app.services.research.graph_reuse import GraphQueryEmbedding, _fact_context_allowed
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed, utc_now


async def shared_graph_has_evidence(session: AsyncSession) -> bool:
    return await graph_has_supported_facts(None)


async def _shared_candidates(session, *, need, embedding, limit):
    return await lookup_candidates(
        customer_id=None,
        question_id=None,
        dense_query=embedding.vector,
        bound=limit,
    )


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
