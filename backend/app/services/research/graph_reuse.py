"""The single research read path for persisted knowledge: Graph v2."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.graph_v2 import GraphFact, GraphFactQuestionDependency, GraphFactSource, GraphNode
from app.observability.events import EVENT_DATASET_RESEARCH, log_event
from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
from app.services.graph_v2.retrieval import FactHit, hybrid_facts, neighbourhood
from app.services.knowledge.embeddings import EmbeddingProvider, require_embedding_vectors
from app.services.research.graph_grounding import fact_is_current, grounded_fact_evidence
from app.services.research.graph_grounding import GraphResearchError
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed, utc_now

logger = logging.getLogger(__name__)


async def lookup_graph_evidence(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    context: ResearchContext,
    embedder: EmbeddingProvider | None = None,
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
        session, need=need, customer_id=customer_id, embedder=embedder, bound=bound
    )
    output: list[ResearchEvidence] = []
    seen: set[str] = set()
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


def _fact_context_allowed(fact: GraphFact, context: ResearchContext) -> bool:
    case_id = fact.attributes.get("knowledge_case_id") or fact.attributes.get("case_id")
    module = fact.attributes.get("knowledge_module") or fact.attributes.get("module")
    return (case_id is None or case_id == context.scope.case_id) and (
        module is None or module == context.scope.module
    )


async def _candidates(session, *, need, customer_id, embedder, bound) -> list[FactHit]:
    scopes = ("shared", f"customer:{customer_id}")
    present = await session.scalar(
        select(GraphFact.id)
        .join(GraphFactSource, GraphFactSource.fact_id == GraphFact.id)
        .where(
            GraphFact.scope_key.in_(scopes),
            GraphFact.status == "active",
            GraphFactSource.source_kind == "text_unit",
        )
        .limit(1)
    )
    if present is None:
        # A verified empty graph requires no embedding call.
        return []
    if embedder is None:
        from app.services.research.composition import research_embeddings

        embedder = research_embeddings()
    raw = (
        await embedder.embed_in_session(session, [need.question])
        if isinstance(
            embedder,
            GraphEmbeddingCacheProvider,
        )
        else await embedder.embed([need.question])
    )
    vectors = require_embedding_vectors(raw, dimension=embedder.dimension)
    if len(vectors) != 1:
        raise GraphResearchError("Graph v2 query embedding count must be one")
    direct = await _question_facts(session, need.knowledge_question_id, scopes, bound)
    hybrid = await hybrid_facts(
        session,
        customer_id=customer_id,
        query=need.question,
        embedding=vectors[0],
        embedding_model=embedder.model,
        limit=bound,
    )
    seeds = list(
        dict.fromkeys(
            node for hit in [*direct, *hybrid] for node in (hit.fact.source_id, hit.fact.target_id)
        )
    )
    expanded = (
        await neighbourhood(
            session,
            customer_id=customer_id,
            seeds=seeds,
            max_hops=1,
            limit=bound,
        )
        if seeds
        else []
    )
    unique: dict[str, FactHit] = {}
    for hit in [*direct, *hybrid, *expanded]:
        unique.setdefault(hit.fact.id, hit)
    return list(unique.values())


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
                "retrieval_reason": "candidates_require_assessment"
                if candidates
                else "no_graph_evidence",
            }
        },
    )


async def _question_facts(session, question_id, scopes, bound) -> list[FactHit]:
    if question_id is None:
        return []
    rows = list(
        (
            await session.scalars(
                select(GraphFact)
                .join(
                    GraphFactQuestionDependency, GraphFactQuestionDependency.fact_id == GraphFact.id
                )
                .join(GraphNode, GraphNode.id == GraphFactQuestionDependency.question_node_id)
                .where(
                    GraphNode.attributes["canonical_question_id"].as_string() == question_id,
                    GraphNode.scope_key.in_(scopes),
                    GraphFact.scope_key.in_(scopes),
                    GraphFactQuestionDependency.scope_key.in_(scopes),
                    GraphFact.status == "active",
                )
                .order_by(GraphFact.id)
                .limit(bound)
            )
        ).all()
    )
    return [FactHit(fact, 1.0, 0) for fact in rows]
