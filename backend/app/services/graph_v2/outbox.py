"""Durable Graph v2 projection queue. No model calls on the research path."""

import logging
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.graph_v2 import GraphIngestWork
from app.services.graph_v2.identity import stable_id
from app.services.graph_v2.jev_judge import JevFactJudge
from app.services.graph_v2.legal_writeback import write_legal_facts
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.relationships import KnowledgeRelationship

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=5)
MAX_ATTEMPTS = 5


async def enqueue_legal_graph(
    session: AsyncSession, *, customer_id: int, research_need_id: str,
    claims: Sequence[KnowledgeClaim], entities: Sequence[KnowledgeEntity],
    relationships: Sequence[KnowledgeRelationship], module: str = "dd",
) -> str | None:
    if not claims:
        return None
    scope_key = claims[0].scope.scope_key
    if any(claim.scope.scope_key != scope_key for claim in claims):
        raise ValueError("graph work cannot mix tenant scopes")
    payload = {
        "module": module,
        "claims": [{"id": c.id, "predicate": c.predicate, "value": c.value,
                    "unit_ids": list(c.supporting_text_unit_ids)} for c in claims],
        "entities": [{"id": e.id, "entity_type": e.entity_type, "key": e.key,
                      "name": e.name, "extra": e.extra} for e in entities],
        "relationships": [{"id": r.id, "relation": r.relation,
                           "from_kind": r.from_kind, "from_id": r.from_id,
                           "to_kind": r.to_kind, "to_id": r.to_id} for r in relationships],
    }
    work_id = stable_id(scope_key, research_need_id, json.dumps(payload, sort_keys=True))
    try:
        async with session.begin_nested():
            session.add(GraphIngestWork(
                id=work_id, customer_id=customer_id, scope_key=scope_key,
                payload=payload, status="pending", attempts=0,
            ))
            await session.flush()
    except IntegrityError:
        if await session.get(GraphIngestWork, work_id) is None:
            raise
    return work_id


def _deserialize(work: GraphIngestWork):
    customer_id = work.customer_id
    payload = work.payload
    claims = [KnowledgeClaim(
        id=row["id"], customer_id=customer_id, predicate=row["predicate"],
        value=row["value"], supporting_text_unit_ids=tuple(row["unit_ids"]),
    ) for row in payload["claims"]]
    entities = [KnowledgeEntity(
        id=row["id"], customer_id=customer_id, entity_type=row["entity_type"],
        key=row["key"], name=row["name"], extra=row["extra"],
    ) for row in payload["entities"]]
    relationships = [KnowledgeRelationship(
        id=row["id"], customer_id=customer_id, relation=row["relation"],
        from_kind=row["from_kind"], from_id=row["from_id"],
        to_kind=row["to_kind"], to_id=row["to_id"], extra={},
    ) for row in payload["relationships"]]
    return claims, entities, relationships, payload["module"]


async def claim_graph_work(factory: async_sessionmaker[AsyncSession]) -> str | None:
    now = datetime.now(UTC)
    async with factory.begin() as session:
        row = await session.scalar(select(GraphIngestWork).where(
            or_(GraphIngestWork.status == "pending",
                (GraphIngestWork.status == "processing")
                & (GraphIngestWork.claimed_at < now - LEASE)),
            GraphIngestWork.attempts < MAX_ATTEMPTS,
        ).order_by(GraphIngestWork.created_at, GraphIngestWork.id)
          .limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        row.status = "processing"
        row.claimed_at = now
        row.attempts += 1
        return row.id


async def process_graph_work(
    factory: async_sessionmaker[AsyncSession], *, limit: int = 50,
    embedder: EmbeddingProvider | None = None, judge: JevFactJudge | None = None,
) -> dict[str, int]:
    completed = failed = 0
    provider = embedder or OpenAIEmbeddingProvider.from_settings()
    for _ in range(limit):
        work_id = await claim_graph_work(factory)
        if work_id is None:
            break
        try:
            async with factory.begin() as session:
                row = await session.get(GraphIngestWork, work_id)
                claims, entities, relationships, module = _deserialize(row)
                await write_legal_facts(
                    session, claims=claims, entities=entities,
                    relationships=relationships, embedder=provider, judge=judge,
                    module=module,
                )
                row.status = "completed"
                row.processed_at = datetime.now(UTC)
                row.last_error = None
            completed += 1
        except Exception as exc:  # One bad projection must not stall the queue.
            logger.exception("graph_v2.ingest_failed work_id=%s", work_id)
            async with factory.begin() as session:
                row = await session.get(GraphIngestWork, work_id)
                row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "pending"
                row.last_error = str(exc)[:2000]
            failed += 1
            # A failed item stays eligible after this batch, but not in a tight loop.
            break
    return {"completed": completed, "failed": failed}
