"""Need canonicalize + reuse lookup. DB work stays under persist_lock."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed
from app.services.research.question_graph import QuestionEvidenceGraph
from app.services.research.question_reuse import (
    safe_canonicalize_research_need,
    safe_lookup_reusable_evidence,
)


async def prepare_need_reuse(
    factory: async_sessionmaker[AsyncSession],
    persist_lock: asyncio.Lock,
    *,
    question_graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
) -> list[ResearchEvidence]:
    """Serialize the prepare session so SQLite StaticPool cannot interleave it."""
    async with persist_lock, factory() as session:
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
