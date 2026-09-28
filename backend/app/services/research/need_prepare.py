"""Need canonicalize + reuse lookup. No persist lock; embeddings may run here."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed
from app.services.research.question_graph import QuestionEvidenceGraph
from app.services.research.question_reuse import (
    safe_canonicalize_research_need,
    safe_lookup_reusable_evidence,
)


async def prepare_need_reuse(
    factory: async_sessionmaker[AsyncSession],
    *,
    question_graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
) -> list[ResearchEvidence]:
    """Match the need and collect reuse candidates without holding persist_lock."""
    async with factory() as session:
        if not need.knowledge_question_id:
            await safe_canonicalize_research_need(
                session,
                graph=question_graph,
                need=need,
                context=context,
            )
            await session.commit()
        return await safe_lookup_reusable_evidence(
            session,
            graph=question_graph,
            need=need,
            context=context,
            exclude_attempt_id=None,
        )
