"""The single research read path for persisted knowledge: Graph v2."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.observability.events import EVENT_DATASET_RESEARCH, log_event
from app.services.knowledge.embeddings import require_embedding_vectors
from app.services.overgraph.model import GraphFactView
from app.services.overgraph.research import graph_has_supported_facts, lookup_candidates
from app.services.research.graph_grounding import fact_is_current, grounded_fact_evidence
from app.services.research.graph_grounding import GraphResearchError
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphQueryEmbedding:
    model: str
    dimension: int
    vector: list[float]


async def lookup_graph_evidence(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    context: ResearchContext,
    query_embedding: GraphQueryEmbedding | None = None,
    limit: int | None = None,
    now: datetime | None = None,
) -> list[ResearchEvidence]:
    customer_id = context.scope.customer_id
    if customer_id is None:
        raise GraphResearchError("Graph v2 research retrieval requires customer_id")
    bound = settings.research_knowledge_lookup_limit if limit is None else limit
    if bound < 1:
        raise ValueError("Graph v2 retrieval limit must be positive")
    current = now or utc_now()
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current
    hits = await _candidates(
        session, need=need, customer_id=customer_id, query_embedding=query_embedding, bound=bound
    )
    from app.services.research.answer_graph import lookup_answers

    output = await lookup_answers(session, need=need, context=context, now=current)
    # Whole answer episodes retain every source; the fact-search cap must not truncate them.
    bound += len(output)
    seen = {str(item.metadata["reuse"]["evidence_ref"]) for item in output}
    for hit in hits:
        if not fact_is_current(hit.fact, current):
            continue
        if not _fact_context_allowed(hit.fact, context):
            continue
        items = await grounded_fact_evidence(
            session,
            fact=hit.fact,
            need=need,
            context=context,
            now=current,
            max_age_seconds=settings.research_knowledge_freshness_max_age_seconds,
        )
        for item in items:
            ref = str(item.metadata["reuse"]["evidence_ref"])
            if ref not in seen and len(output) < bound:
                seen.add(ref)
                output.append(item)
        if len(output) == bound:
            break
    log_event(
        logger,
        "research.graph_v2.retrieval.completed",
        dataset=EVENT_DATASET_RESEARCH,
        outcome="success",
        fields={
            "research": {
                "research_need_id": need.id,
                "graph_candidate_count": len(hits),
                "graph_evidence_count": len(output),
                "retrieval_provider": "graph_v2",
            }
        },
    )
    return output


def _fact_context_allowed(fact: GraphFactView, context: ResearchContext) -> bool:
    from app.services.research.workspace_grounding import fact_workspace_allowed

    if not fact_workspace_allowed(fact, context):
        return False
    case_id = fact.attributes.get("knowledge_case_id") or fact.attributes.get("case_id")
    module = fact.attributes.get("knowledge_module") or fact.attributes.get("module")
    return (case_id is None or case_id == context.scope.case_id) and (
        module is None or module == context.scope.module
    )


async def _candidates(session, *, need, customer_id, query_embedding, bound):
    if not await graph_has_supported_facts(customer_id):
        # A verified empty graph requires no embedding call.
        return []
    if query_embedding is None:
        raise GraphResearchError("Prepare query embedding before opening the Graph read transaction")
    vectors = require_embedding_vectors([query_embedding.vector], dimension=query_embedding.dimension)
    return await lookup_candidates(
        customer_id=customer_id,
        question_id=need.knowledge_question_id,
        dense_query=vectors[0],
        bound=bound,
    )


def log_external_search(need: ResearchNeed, candidates: list[ResearchEvidence]) -> None:
    log_event(
        logger,
        "research.graph_v2.external_search",
        dataset=EVENT_DATASET_RESEARCH,
        outcome="unknown",
        fields={
            "research": {
                "research_need_id": need.id,
                "graph_evidence_count": len(candidates),
                "source_types": need.source_types,
                "retrieval_reason": "insufficient_graph_answer"
                if candidates
                else "no_graph_evidence",
            }
        },
    )


