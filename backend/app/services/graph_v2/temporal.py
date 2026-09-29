"""Explicit invalidation with structural and temporal guards."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact
from app.services.graph_v2.errors import PermanentGraphError


async def invalidate_fact(
    session: AsyncSession, *, prior_id: str, successor_id: str, at: datetime,
) -> GraphFact:
    prior = await session.get(GraphFact, prior_id)
    successor = await session.get(GraphFact, successor_id)
    if prior is None or successor is None or prior.id == successor.id:
        raise PermanentGraphError("invalidation requires two distinct persisted facts")
    guard = (
        "scope_key", "source_id", "target_id", "predicate", "context_id", "occurrence_key",
    )
    if any(getattr(prior, field) != getattr(successor, field) for field in guard):
        raise PermanentGraphError("invalidation requires matching scope, endpoints, predicate and occurrence")
    if prior.status != "active" or successor.status != "active":
        raise PermanentGraphError("invalidation requires active facts")
    if prior.valid_at is not None and at < prior.valid_at:
        raise PermanentGraphError("invalidation precedes fact validity")
    if successor.valid_at is not None and at < successor.valid_at:
        raise PermanentGraphError("invalidation precedes successor validity")
    prior.invalid_at = at
    prior.status = "invalidated"
    await session.flush()
    return prior
