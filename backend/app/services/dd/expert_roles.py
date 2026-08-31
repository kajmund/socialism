"""Load DD expert roles from kind=expert Persona rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Persona, Population, PopulationMember
from app.serializers import profile_from_dict
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.dd.expert_keys import expert_role_key
from app.services.expert_tools import resolve_expert_tools
from app.services.panel.schemas import PanelExpertSlot


def _profile_text(persona: Persona) -> str:
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


async def load_expert_slots(
    session: AsyncSession,
    *,
    customer_id: int,
    role_keys: list[str] | None = None,
) -> list[PanelExpertSlot]:
    """Resolve expert slots from Persona rows scoped to the DD campaign customer."""
    await ensure_default_expert_personas(session, customer_id=customer_id)

    result = await session.execute(
        select(Persona).where(
            Persona.kind == "expert",
            Persona.customer_id == customer_id,
        )
    )
    personas = list(result.scalars().all())
    if not personas:
        raise RuntimeError(f"No expert personas for customer_id={customer_id}")

    by_key = {expert_role_key(p.name): p for p in personas}
    selected_keys = role_keys or list(by_key.keys())
    slots: list[PanelExpertSlot] = []
    for key in selected_keys:
        persona = by_key.get(key)
        if persona is None:
            raise RuntimeError(f"Unknown DD expert role key: {key}")
        slots.append(
            PanelExpertSlot(
                slot_id=key,
                label=persona.name,
                profile=_profile_text(persona),
                tools=resolve_expert_tools(persona.tools),
            )
        )
    return slots


async def load_expert_slots_from_population(
    session: AsyncSession,
    population_id: int,
) -> list[PanelExpertSlot]:
    """Resolve expert slots from a saved expert_panel population."""
    result = await session.execute(
        select(Population)
        .options(selectinload(Population.members).selectinload(PopulationMember.persona))
        .where(Population.id == population_id)
    )
    population = result.scalar_one_or_none()
    if population is None:
        raise RuntimeError(f"Population not found: {population_id}")
    if population.kind != "expert_panel":
        raise RuntimeError(f"Population {population_id} is not an expert panel")

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
                profile=_profile_text(persona),
                tools=resolve_expert_tools(persona.tools),
            )
        )
    if not slots:
        raise RuntimeError(f"Expert panel {population_id} has no members")
    return slots
