"""Queue lagen.nu graph writes until every document for a source is interpreted."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

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


@dataclass
class GraphWritebackQueue:
    _pending: list[PendingGraphWrite] = field(default_factory=list)

    def enqueue(self, item: PendingGraphWrite) -> None:
        self._pending.append(item)

    def enqueue_grounded(
        self,
        *,
        claims: Sequence[KnowledgeClaim],
        entities: Sequence[KnowledgeEntity],
        edges: Sequence[KnowledgeRelationship],
        research_need_id: str,
        question: str,
        source_type: str,
        customer_id: int,
    ) -> None:
        self.enqueue(
            PendingGraphWrite(
                claims=tuple(claims),
                entities=tuple(entities),
                edges=tuple(edges),
                research_need_id=research_need_id,
                question=question,
                source_type=source_type,
                customer_id=customer_id,
            )
        )

    def take(self) -> list[PendingGraphWrite]:
        pending = self._pending
        self._pending = []
        return pending


async def persist_pending_graph_writes(
    session: AsyncSession,
    items: Sequence[PendingGraphWrite],
) -> tuple[int, list[str], list[str]]:
    """Persist queued claims and edges. Returns customer_id plus node ids."""
    if not items:
        return 0, [], []
    customer_ids = {item.customer_id for item in items}
    if len(customer_ids) != 1:
        raise ValueError("graph write-back mixed customer_id values")
    customer_id = items[0].customer_id
    claim_ids: list[str] = []
    relationship_ids: list[str] = []
    for item in items:
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
        claim_ids.extend(claim.id for claim in item.claims)
        relationship_ids.extend(edge.id for edge in item.edges)
    return customer_id, claim_ids, relationship_ids


async def flush_graph_writeback(
    session: AsyncSession | None,
    queue: GraphWritebackQueue,
    *,
    release_connection: Callable[[AsyncSession], Awaitable[None]],
    revalidate: Callable[..., Awaitable[None]],
) -> None:
    pending = queue.take()
    if not pending:
        return
    if session is None:
        raise LagenNuResearchKnowledgeError(
            "lagen.nu research requires session and customer_id to persist claims"
        )
    customer_id, claim_ids, relationship_ids = await persist_pending_graph_writes(
        session, pending
    )
    # Shared entity keys become visible to concurrent needs after this commit.
    await release_connection(session)
    await revalidate(
        customer_id=customer_id,
        claim_ids=claim_ids,
        relationship_ids=relationship_ids,
    )
