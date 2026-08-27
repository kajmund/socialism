"""Load DD expert roles from the dd_expertpanel catalog."""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.domain import CatalogItem
from app.services.catalog_items import coerce_catalog_items
from app.services.catalog_store import ensure_catalog_defaults, get_catalog_list
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_store import MissingActiveConfigurationError, get_active_configuration

_EXPERT_KEY_RE = re.compile(r"[^a-z0-9]+")


def expert_role_key(label: str) -> str:
    slug = _EXPERT_KEY_RE.sub("_", label.strip().casefold()).strip("_")
    return slug or "expert"


def _profile_text(item: CatalogItem) -> str:
    lines = [
        item.description,
        f"Kompetensområde: {item.kompetensomrade}" if item.kompetensomrade else "",
        f"Rådgivningsstil: {item.radgivningsstil}" if item.radgivningsstil else "",
        f"Yrkesbakgrund: {item.yrkesbakgrund}" if item.yrkesbakgrund else "",
        f"Anekdot: {item.professionell_anekdot}" if item.professionell_anekdot else "",
    ]
    return "\n".join(line for line in lines if line).strip()


async def load_expert_slots(
    session: AsyncSession,
    *,
    role_keys: list[str] | None = None,
) -> list[PanelExpertSlot]:
    """Resolve expert slots from active configuration's dd_expertpanel catalog."""
    active = await get_active_configuration(session)
    if active is None:
        raise MissingActiveConfigurationError("No active configuration")
    await ensure_catalog_defaults(session, active.id)
    row = await get_catalog_list(session, active.id, "expert_roller")
    if row is None:
        raise RuntimeError("DD expertpanel catalog missing on active configuration")

    items = coerce_catalog_items(row.items)
    if not items:
        raise RuntimeError("DD expertpanel catalog has no roles")

    by_key = {expert_role_key(item.label): item for item in items}
    selected_keys = role_keys or list(by_key.keys())
    slots: list[PanelExpertSlot] = []
    for key in selected_keys:
        item = by_key.get(key)
        if item is None:
            raise RuntimeError(f"Unknown DD expert role key: {key}")
        slots.append(
            PanelExpertSlot(
                slot_id=key,
                label=item.label,
                profile=_profile_text(item),
            )
        )
    return slots
