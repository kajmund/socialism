"""Persistent storage for population generate → preview → create staging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PopulationGeneration
from app.schemas.domain import GenerationCandidate, PopulationRecipe

GENERATION_TTL = timedelta(days=7)


@dataclass
class StoredGeneration:
    recipe: PopulationRecipe
    fingerprint: list[list[int]]
    candidates: list[GenerationCandidate] = field(default_factory=list)
    qa_warnings: list[str] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def clear_generations(session: AsyncSession) -> None:
    await session.execute(delete(PopulationGeneration))


async def get_generation(session: AsyncSession, generation_id: str) -> StoredGeneration | None:
    row = await session.get(PopulationGeneration, generation_id)
    if row is None:
        return None
    if row.consumed_at is not None:
        return None
    return StoredGeneration(
        recipe=PopulationRecipe.model_validate(row.recipe),
        fingerprint=list(row.fingerprint or []),
        candidates=[GenerationCandidate.model_validate(c) for c in row.candidates or []],
        qa_warnings=list(row.qa_warnings or []),
    )


async def put_generation(
    session: AsyncSession,
    generation_id: str,
    stored: StoredGeneration,
) -> None:
    await _expire_old_generations(session)
    existing = await session.get(PopulationGeneration, generation_id)
    payload = {
        "recipe": stored.recipe.model_dump(),
        "fingerprint": stored.fingerprint,
        "candidates": [c.model_dump() for c in stored.candidates],
        "qa_warnings": stored.qa_warnings,
        "consumed_at": None,
    }
    if existing is None:
        session.add(PopulationGeneration(id=generation_id, **payload))
    else:
        for key, value in payload.items():
            setattr(existing, key, value)


async def pop_generation(session: AsyncSession, generation_id: str) -> StoredGeneration | None:
    stored = await get_generation(session, generation_id)
    if stored is None:
        return None
    row = await session.get(PopulationGeneration, generation_id)
    if row is not None:
        row.consumed_at = _utcnow()
    return stored


async def _expire_old_generations(session: AsyncSession) -> None:
    cutoff = _utcnow() - GENERATION_TTL
    await session.execute(
        delete(PopulationGeneration).where(PopulationGeneration.created_at < cutoff)
    )
