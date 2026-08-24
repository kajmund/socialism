"""Persist and read Run.live_progress_* for realtime catch-up."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Run

LIVE_PROGRESS_VARIANTS = ("main", "a", "b")


def live_progress_column(variant_id: str) -> str:
    if variant_id not in LIVE_PROGRESS_VARIANTS:
        raise ValueError(f"Unknown variant_id for live_progress: {variant_id!r}")
    return f"live_progress_{variant_id}"


def read_live_progress(run: Run, variant_id: str) -> list[dict[str, Any]]:
    raw = getattr(run, live_progress_column(variant_id), None)
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


async def reset_live_progress(
    session: AsyncSession,
    run: Run,
    variant_ids: list[str],
) -> None:
    for variant_id in variant_ids:
        setattr(run, live_progress_column(variant_id), [])
    await session.commit()


async def append_live_progress_entry(
    session: AsyncSession,
    *,
    run_id: int,
    variant_id: str,
    entry: dict[str, Any],
) -> None:
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    col = live_progress_column(variant_id)
    current = list(getattr(run, col) or [])
    current.append(entry)
    setattr(run, col, current)
    await session.commit()
