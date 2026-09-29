"""Durable Graph v2 projection queue. No model calls on the research path."""

import logging
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.graph_v2 import GraphIngestWork
from app.services.graph_v2.identity import stable_id
from app.services.graph_v2.jev_judge import JevFactJudge, JevNodeJudge
from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.legal_writeback import write_legal_facts
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from app.services.knowledge.entities import KnowledgeEntity

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=5)


async def enqueue_legal_graph(
    session: AsyncSession, *, customer_id: int, research_need_id: str,
    claims: Sequence[KnowledgeClaim], entities: Sequence[KnowledgeEntity],
    module: str = "dd",
) -> str | None:
    if not claims:
        return None
    scope_key = claims[0].scope.scope_key
    if any(claim.scope.scope_key != scope_key for claim in claims):
        raise PermanentGraphError("graph work cannot mix tenant scopes")
    payload = {
        "module": module,
        "claims": [{"id": c.id, "predicate": c.predicate, "value": c.value,
                    "unit_ids": list(c.supporting_text_unit_ids)} for c in claims],
        "entities": [{"id": e.id, "entity_type": e.entity_type, "key": e.key,
                      "name": e.name, "extra": e.extra} for e in entities],
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
    try:
        claims = [KnowledgeClaim(
            id=row["id"], customer_id=customer_id, predicate=row["predicate"],
            value=row["value"], supporting_text_unit_ids=tuple(row["unit_ids"]),
        ) for row in payload["claims"]]
        entities = [KnowledgeEntity(
            id=row["id"], customer_id=customer_id, entity_type=row["entity_type"],
            key=row["key"], name=row["name"], extra=row["extra"],
        ) for row in payload["entities"]]
        module = payload["module"]
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise PermanentGraphError("invalid persisted Graph v2 work payload") from exc
    return claims, entities, module


async def claim_graph_work(factory: async_sessionmaker[AsyncSession]) -> tuple[str, int] | None:
    now = datetime.now(UTC)
    async with factory.begin() as session:
        row = await session.scalar(select(GraphIngestWork).where(
            or_(GraphIngestWork.status == "pending",
                (GraphIngestWork.status == "processing")
                & (GraphIngestWork.claimed_at < now - LEASE)),
            or_(GraphIngestWork.retry_at.is_(None), GraphIngestWork.retry_at <= now),
        ).order_by(GraphIngestWork.created_at, GraphIngestWork.id)
          .limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        row.status = "processing"
        row.claimed_at = now
        row.retry_at = None
        row.attempts += 1
        return row.id, row.attempts


async def process_graph_work(
    factory: async_sessionmaker[AsyncSession], *, limit: int = 50,
    embedder: EmbeddingProvider | None = None, judge: JevFactJudge | None = None,
    node_judge: JevNodeJudge | None = None,
) -> dict[str, int]:
    completed = failed = 0
    inner = embedder or OpenAIEmbeddingProvider.from_settings()
    provider = inner if isinstance(inner, GraphEmbeddingCacheProvider) else GraphEmbeddingCacheProvider(factory, inner)
    for _ in range(limit):
        claim = await claim_graph_work(factory)
        if claim is None:
            break
        work_id, attempt = claim
        try:
            async with factory.begin() as session:
                row = await session.get(GraphIngestWork, work_id)
                claims, entities, module = _deserialize(row)
                await write_legal_facts(
                    session, claims=claims, entities=entities,
                    embedder=provider, judge=judge, node_judge=node_judge,
                    module=module,
                )
                result = await session.execute(update(GraphIngestWork).where(
                    GraphIngestWork.id == work_id,
                    GraphIngestWork.status == "processing",
                    GraphIngestWork.attempts == attempt,
                ).values(status="completed", processed_at=datetime.now(UTC),
                         retry_at=None, last_error=None))
            completed += int(result.rowcount == 1)
        except Exception as exc:  # One bad projection must not stall the queue.
            if _is_permanent_graph_error(exc):
                logger.exception(
                    "graph_v2.ingest_terminal work_id=%s error_type=%s",
                    work_id, type(exc).__name__,
                )
                await _fail_graph_work(factory, work_id, attempt, exc)
            else:
                logger.exception(
                    "graph_v2.ingest_retryable work_id=%s error_type=%s",
                    work_id, type(exc).__name__,
                )
                await _retry_graph_work(factory, work_id, attempt, exc)
            failed += 1
            # A failed item stays eligible after this batch, but not in a tight loop.
            break
    return {"completed": completed, "failed": failed}


def _is_permanent_graph_error(exc: Exception) -> bool:
    """Payload, invariant, and data-shape failures cannot heal on retry."""
    return isinstance(exc, (PermanentGraphError, DataError, ProgrammingError))


async def _fail_graph_work(
    factory: async_sessionmaker[AsyncSession], work_id: str,
    attempt: int, exc: Exception,
) -> None:
    async with factory.begin() as session:
        await session.execute(update(GraphIngestWork).where(
            GraphIngestWork.id == work_id,
            GraphIngestWork.status == "processing",
            GraphIngestWork.attempts == attempt,
        ).values(status="failed", retry_at=None, last_error=str(exc)[:2000]))


async def _retry_graph_work(
    factory: async_sessionmaker[AsyncSession], work_id: str,
    attempt: int, exc: Exception,
) -> None:
    delay = min(5 * 2 ** min(attempt - 1, 7), 600)
    async with factory.begin() as session:
        await session.execute(update(GraphIngestWork).where(
            GraphIngestWork.id == work_id,
            GraphIngestWork.status == "processing",
            GraphIngestWork.attempts == attempt,
        ).values(status="pending", retry_at=datetime.now(UTC) + timedelta(seconds=delay),
                 last_error=str(exc)[:2000]))
