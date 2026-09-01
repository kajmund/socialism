"""Load DD expert roles from kind=expert Persona rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.dd.expert_keys import expert_role_key
from app.services.expert_tools import resolve_expert_tools
from app.services.panel.expert_slots import profile_text_for_expert
from app.services.panel.schemas import PanelExpertSlot
from app.services.panel.spinndoctor_profile import SPINNDOCTOR_KEY


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
    selected_keys = role_keys or [key for key in by_key if key != SPINNDOCTOR_KEY]
    slots: list[PanelExpertSlot] = []
    for key in selected_keys:
        persona = by_key.get(key)
        if persona is None:
            raise RuntimeError(f"Unknown DD expert role key: {key}")
        slots.append(
            PanelExpertSlot(
                slot_id=key,
                label=persona.name,
                profile=profile_text_for_expert(persona),
                tools=resolve_expert_tools(persona.tools),
            )
        )
    return slots
