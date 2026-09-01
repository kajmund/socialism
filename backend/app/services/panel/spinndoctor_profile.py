"""Shared Spinndoktor catalog row (report-chat identity). Not the DD panel moderator."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelExpertProfile
from app.services.panel.expert_profiles_store import (
    ensure_expert_profile_defaults,
    get_expert_profile_by_key,
)

SPINNDOCTOR_KEY = "spinndoctor"
SPINNDOCTOR_MODULES = ("dd", "politik")

SPINNDOCTOR_SPEC: dict[str, str] = {
    "key": SPINNDOCTOR_KEY,
    "name": "Spinndoktor",
    "description": (
        "Erfaren svensk kommunikationsrådgivare som hjälper användaren tolka "
        "en specifik simulerings- eller DD-rapport. Agerar först, frågar sist."
    ),
    "kompetensomrade": "Politisk kommunikation och rapporttolkning",
    "radgivningsstil": "Konkret, jordnära, slutsats först",
    "yrkesbakgrund": "Kommunikationsrådgivare",
    "professionell_anekdot": "Slår upp det som går att slå upp innan hen frågar användaren.",
}


def catalog_profile_text(row: PanelExpertProfile) -> str:
    lines = [
        row.description,
        f"Kompetensområde: {row.kompetensomrade}" if row.kompetensomrade else "",
        f"Rådgivningsstil: {row.radgivningsstil}" if row.radgivningsstil else "",
        f"Yrkesbakgrund: {row.yrkesbakgrund}" if row.yrkesbakgrund else "",
        f"Anekdot: {row.professionell_anekdot}" if row.professionell_anekdot else "",
    ]
    return "\n".join(line for line in lines if line).strip()


async def ensure_spinndoctor_profile(session: AsyncSession) -> int:
    added = 0
    for module_id in SPINNDOCTOR_MODULES:
        added += await ensure_expert_profile_defaults(session, module_id, [SPINNDOCTOR_SPEC])
    return added


async def require_spinndoctor_profile(session: AsyncSession) -> PanelExpertProfile:
    row = await get_expert_profile_by_key(session, SPINNDOCTOR_KEY)
    if row is None or not row.active:
        raise RuntimeError("Spinndoktor expert profile is not seeded")
    return row
