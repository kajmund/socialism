"""Load DD expert roles from kind=expert Persona rows."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.serializers import profile_from_dict
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.panel.schemas import PanelExpertSlot

_EXPERT_KEY_RE = re.compile(r"[^a-z0-9]+")


def expert_role_key(label: str) -> str:
    slug = _EXPERT_KEY_RE.sub("_", label.strip().casefold()).strip("_")
    return slug or "expert"


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
            )
        )
    return slots
