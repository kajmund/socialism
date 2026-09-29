"""Queue lagen.nu graph writes until every document for a source is interpreted."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.lagen_nu.text_unit_research import LagenNuResearchKnowledgeError

from app.database.models import TextUnitRecord
from app.services.knowledge.claims import KnowledgeClaim, answer_research_need
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.observations import KnowledgeObservation
from app.services.knowledge.persist import persist_extracted_knowledge
from app.services.knowledge.relationships import KnowledgeRelationship
from app.services.graph_v2.outbox import enqueue_legal_graph
from app.services.lagen_nu.claim_grounding import GroundedLegalKnowledge, ground_legal_extraction
from app.services.lagen_nu.legal_graph import ground_legal_graph
from app.services.legal_research_result import LegalResearchResult
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
    module: str = "dd"
    observations: tuple[KnowledgeObservation, ...] = ()


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


@dataclass(frozen=True)
class LegalWriteContext:
    customer_id: int
    research_need_id: str
    result_id: str
    question: str
    source_type: str
    module: str = "dd"


def queue_legal_knowledge(
    queue: GraphWritebackQueue,
    result: LegalResearchResult,
    units: Sequence[TextUnitRecord],
    context: LegalWriteContext,
) -> GroundedLegalKnowledge:
    extracted = ground_legal_extraction(
        result,
        units,
        customer_id=context.customer_id,
        research_need_id=context.research_need_id,
        result_id=context.result_id,
        question=context.question,
    )
    entities, edges = ground_legal_graph(
        result,
        extracted.claims,
        customer_id=context.customer_id,
        document_id=units[0].document_id,
    )
    queue.enqueue(
        PendingGraphWrite(
            claims=extracted.claims,
            entities=tuple(entities),
            edges=tuple(edges),
            research_need_id=context.research_need_id,
            question=context.question,
            source_type=context.source_type,
            customer_id=context.customer_id,
            module=context.module,
            observations=extracted.observations,
        )
    )
    return extracted


async def persist_pending_graph_writes(
    session: AsyncSession,
    items: Sequence[PendingGraphWrite],
) -> None:
    """Persist claims, edges and answer links in one transaction."""
    if not items:
        return
    customer_ids = {item.customer_id for item in items}
    if len(customer_ids) != 1:
        raise ValueError("graph write-back mixed customer_id values")
    for item in items:
        if any(claim.customer_id != item.customer_id for claim in item.claims):
            raise ValueError("claims must belong to the write-back customer_id")
        persisted = await persist_extracted_knowledge(
            session,
            claims=item.claims,
            entities=item.entities,
            relationships=item.edges,
            observations=item.observations,
            question_key=research_question_key(item.question),
        )
        if persisted.accepted_claim_ids:
            accepted = set(persisted.accepted_claim_ids)
            await enqueue_legal_graph(
                session, customer_id=item.customer_id,
                research_need_id=item.research_need_id,
                claims=tuple(claim for claim in item.claims if claim.id in accepted),
                entities=item.entities, relationships=item.edges, module=item.module,
            )
            await answer_research_need(
                session,
                research_need_id=item.research_need_id,
                question_key=research_question_key(item.question),
                claim_ids=persisted.accepted_claim_ids,
                source_type=item.source_type,
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
