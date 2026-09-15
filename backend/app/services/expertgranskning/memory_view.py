"""Serialize expert-memory hits for API and chat payloads."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.schemas.domain import ExpertMemoryExpertOut, ExpertMemoryOut
from app.services.expertgranskning.memory import ExpertMemoryHit, memory_image_sha256

_EXPERT_KEY_RE = re.compile(r"[^a-z0-9]+")


def _catalog_key(persona: Persona) -> str:
    prefix = f"exp_{persona.customer_id}_"
    if persona.id.startswith(prefix):
        return persona.id[len(prefix) :]
    if persona.id.startswith("exp_"):
        return persona.id[4:]
    slug = _EXPERT_KEY_RE.sub("_", persona.name.strip().casefold()).strip("_")
    return slug or "expert"


def serialize_memory_hit(
    hit: ExpertMemoryHit,
    *,
    customer_id: int | None = None,
    expert_name: str = "",
    persona_id: str | None = None,
) -> ExpertMemoryOut:
    return ExpertMemoryOut(
        id=hit.id,
        text=hit.text,
        source=hit.source,
        expert_id=hit.expert_id,
        expert_name=expert_name,
        persona_id=persona_id,
        customer_id=customer_id,
        created_at=hit.created_at,
        updated_at=hit.updated_at,
        event=hit.event,
        image_sha256=memory_image_sha256(hit.metadata),
    )


async def expert_directory(
    session: AsyncSession,
    *,
    customer_id: int | None = None,
) -> dict[tuple[int, str], tuple[str, str]]:
    """Map (customer_id, catalog_key) → (name, persona_id)."""
    stmt = select(Persona).where(Persona.kind == "expert")
    if customer_id is not None:
        stmt = stmt.where(Persona.customer_id == customer_id)
    result = await session.execute(stmt)
    directory: dict[tuple[int, str], tuple[str, str]] = {}
    for persona in result.scalars().all():
        directory[(persona.customer_id, _catalog_key(persona))] = (
            persona.name,
            persona.id,
        )
    return directory


def attach_expert_labels(
    hits: list[ExpertMemoryHit],
    directory: dict[tuple[int, str], tuple[str, str]],
    *,
    customer_id: int,
) -> list[ExpertMemoryOut]:
    rows: list[ExpertMemoryOut] = []
    for hit in hits:
        name, persona_id = directory.get((customer_id, hit.expert_id), ("", None))
        rows.append(
            serialize_memory_hit(
                hit,
                customer_id=customer_id,
                expert_name=name,
                persona_id=persona_id,
            )
        )
    rows.sort(key=lambda row: (row.updated_at or row.created_at or "", row.id), reverse=True)
    return rows


async def labeled_memory(
    session: AsyncSession,
    hit: ExpertMemoryHit,
    *,
    customer_id: int,
) -> ExpertMemoryOut:
    directory = await expert_directory(session, customer_id=customer_id)
    labeled = attach_expert_labels([hit], directory, customer_id=customer_id)
    return labeled[0]


def directory_experts(
    directory: dict[tuple[int, str], tuple[str, str]],
    *,
    customer_id: int | None = None,
) -> list[ExpertMemoryExpertOut]:
    rows = [
        ExpertMemoryExpertOut(
            expert_id=expert_id,
            name=name,
            persona_id=persona_id,
            customer_id=kund_id,
        )
        for (kund_id, expert_id), (name, persona_id) in directory.items()
        if customer_id is None or kund_id == customer_id
    ]
    rows.sort(key=lambda row: (row.name, row.expert_id))
    return rows
