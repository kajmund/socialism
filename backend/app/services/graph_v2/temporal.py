"""Explicit invalidation with structural and temporal guards."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact


async def invalidate_fact(
    session: AsyncSession, *, prior_id: str, successor_id: str, at: datetime,
) -> GraphFact:
    prior = await session.get(GraphFact, prior_id)
    successor = await session.get(GraphFact, successor_id)
    if prior is None or successor is None or prior.id == successor.id:
        raise ValueError("invalidation requires two distinct persisted facts")
    guard = (
        "scope_key", "source_id", "target_id", "predicate", "context_id", "occurrence_key",
    )
    if any(getattr(prior, field) != getattr(successor, field) for field in guard):
        raise ValueError("invalidation requires matching scope, endpoints, predicate and occurrence")
    if prior.status != "active" or successor.status != "active":
        raise ValueError("invalidation requires active facts")
    if prior.valid_at is not None and at < prior.valid_at:
        raise ValueError("invalidation precedes fact validity")
    if successor.valid_at is not None and at < successor.valid_at:
        raise ValueError("invalidation precedes successor validity")
    prior.invalid_at = at
    prior.status = "invalidated"
    await session.flush()
    return prior
