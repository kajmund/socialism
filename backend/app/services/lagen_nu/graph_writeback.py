"""Queue lagen.nu graph writes until every document for a source is interpreted."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.answer_review import AnswerReviewDecision, schedule_answer_review
from app.services.lagen_nu.text_unit_research import LagenNuResearchKnowledgeError

from app.services.knowledge.claims import (
    KnowledgeClaim,
    answer_research_need,
    persist_knowledge_claims,
)
from app.services.knowledge.entities import KnowledgeEntity, persist_knowledge_entities
from app.services.knowledge.relationships import (
    KnowledgeRelationship,
    persist_knowledge_relationships,
)
from app.services.research.knowledge_question import research_question_key


@dataclass(frozen=True)
class PendingGraphWrite:
    claims: tuple[KnowledgeClaim, ...]
    entities: tuple[KnowledgeEntity, ...]
    edges: tuple[KnowledgeRelationship, ...]
    research_need_id: str
    question: str
    source_type: str
    customer_id: int
    review_decision: AnswerReviewDecision


@dataclass
class GraphWritebackQueue:
    _pending: list[PendingGraphWrite] = field(default_factory=list)
    session_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def enqueue(self, item: PendingGraphWrite) -> None:
        self._pending.append(item)

    def take(self) -> list[PendingGraphWrite]:
        pending = self._pending
        self._pending = []
        return pending


async def persist_pending_graph_writes(
    session: AsyncSession,
    items: Sequence[PendingGraphWrite],
) -> None:
    """Persist claims, edges and their review schedules in one transaction."""
    if not items:
        return
    customer_ids = {item.customer_id for item in items}
    if len(customer_ids) != 1:
        raise ValueError("graph write-back mixed customer_id values")
    for item in items:
        if any(claim.customer_id != item.customer_id for claim in item.claims):
            raise ValueError("answer review claims must belong to the write-back customer_id")
        await persist_knowledge_claims(session, item.claims)
        await persist_knowledge_entities(session, item.entities)
        await persist_knowledge_relationships(session, item.edges)
        await answer_research_need(
            session,
            research_need_id=item.research_need_id,
            question_key=research_question_key(item.question),
            claim_ids=[claim.id for claim in item.claims],
            source_type=item.source_type,
        )
        await schedule_answer_review(
            session,
            customer_id=item.customer_id,
            question_key=research_question_key(item.question),
            question=item.question,
            claim_ids=[claim.id for claim in item.claims],
            decision=item.review_decision,
        )


async def flush_graph_writeback(
    session: AsyncSession | None,
    queue: GraphWritebackQueue,
    *,
    release_connection: Callable[[AsyncSession], Awaitable[None]],
) -> None:
    pending = queue.take()
    if not pending:
        return
    if session is None:
        raise LagenNuResearchKnowledgeError(
            "lagen.nu research requires session and customer_id to persist claims"
        )
    await persist_pending_graph_writes(session, pending)
    # Shared entity keys become visible to concurrent needs after this commit.
    await release_connection(session)
