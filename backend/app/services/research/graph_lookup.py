"""Own the graph read transaction; query embeddings never retain its connection."""

from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.graph_v2 import GraphFact, GraphFactSource
from app.services.knowledge.embeddings import EmbeddingProvider, require_embedding_vectors
from app.services.research.graph_reuse import lookup_graph_evidence, GraphQueryEmbedding
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed


async def lookup_question(
    factory: async_sessionmaker[AsyncSession],
    need: ResearchNeed,
    context: ResearchContext,
    embeddings: EmbeddingProvider | None = None,
    *,
    timings: dict[str, float] | None = None,
) -> list[ResearchEvidence]:
    scopes = ("shared", f"customer:{context.scope.customer_id}")
    async with factory() as session:
        present = await session.scalar(
            select(GraphFact.id)
            .join(
                GraphFactSource,
                GraphFactSource.fact_id == GraphFact.id,
            )
            .where(
                GraphFact.scope_key.in_(scopes),
                GraphFact.status == "active",
                GraphFactSource.source_kind == "text_unit",
            )
            .limit(1)
        )
    prepared = None
    if present:
        if embeddings is None:
            from app.services.research.composition import research_embeddings

            embeddings = research_embeddings()
        started = perf_counter()
        vectors = require_embedding_vectors(
            await embeddings.embed([need.question]),
            dimension=embeddings.dimension,
        )
        if len(vectors) != 1:
            raise ValueError("Query embedding must contain one vector")
        prepared = GraphQueryEmbedding(embeddings.model, embeddings.dimension, vectors[0])
        if timings is not None:
            timings["embedding"] = perf_counter() - started
    started = perf_counter()
    async with factory() as session:
        result = await lookup_graph_evidence(
            session, need=need, context=context, query_embedding=prepared
        )
    if timings is not None:
        timings["graph_read"] = perf_counter() - started
    return result
