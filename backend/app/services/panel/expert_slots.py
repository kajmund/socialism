"""Resolve expert slots from a saved expert_panel population."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Persona, Population, PopulationMember, Projekt
from app.serializers import profile_from_dict
from app.services.dd.expert_keys import expert_role_key
from app.services.expert_tools import resolve_expert_tools
from app.services.panel.schemas import PanelExpertSlot


def profile_text_for_expert(persona: Persona) -> str:
    profile = profile_from_dict(persona.profile if isinstance(persona.profile, dict) else None, persona.name)
    description = persona.quote if persona.quote else profile.beskrivning
    lines = [
        description if description not in ("", "—") else "",
        f"Kompetensområde: {profile.kompetensomrade}" if profile.kompetensomrade not in ("", "—") else "",
        f"Rådgivningsstil: {profile.radgivningsstil}" if profile.radgivningsstil not in ("", "—") else "",
        f"Yrkesbakgrund: {profile.yrkesbakgrund or persona.occ}"
        if (profile.yrkesbakgrund or persona.occ) not in ("", "—")
        else "",
        f"Anekdot: {profile.professionell_anekdot}"
        if profile.professionell_anekdot not in ("", "—")
        else "",
    ]
    return "\n".join(line for line in lines if line).strip()


async def require_expert_panel(session: AsyncSession, panel_id: int) -> Population:
    result = await session.execute(
        select(Population)
        .options(selectinload(Population.members).selectinload(PopulationMember.persona))
        .where(Population.id == panel_id)
    )
    population = result.scalar_one_or_none()
    if population is None:
        raise LookupError(f"Panel not found: {panel_id}")
    if population.kind != "expert_panel":
        raise ValueError(f"Population {panel_id} is not an expert panel")
    return population


async def require_project(session: AsyncSession, project_id: int) -> Projekt:
    row = await session.get(Projekt, project_id)
    if row is None:
        raise LookupError(f"Project not found: {project_id}")
    return row


async def load_expert_slots_from_population(
    session: AsyncSession,
    population_id: int,
) -> list[PanelExpertSlot]:
    """Resolve expert slots from a saved expert_panel population."""
    population = await require_expert_panel(session, population_id)
    slots: list[PanelExpertSlot] = []
    for member in population.members:
        persona = member.persona
        if persona is None:
            raise RuntimeError(f"Expert panel member missing persona: {member.id}")
        key = expert_role_key(persona.name)
        slots.append(
            PanelExpertSlot(
                slot_id=key,
                label=persona.name,
                profile=profile_text_for_expert(persona),
                tools=resolve_expert_tools(persona.tools),
            )
        )
    if not slots:
        raise RuntimeError(f"Expert panel {population_id} has no members")
    return slots
