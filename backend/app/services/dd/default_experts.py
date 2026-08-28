"""Default DD expert personas (migrated from dd_expertpanel catalog)."""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.schemas.domain import EditablePersona
from app.serializers import persona_initials, utcnow
from app.services.kund_store import bolag_demo_customer_id

_EXPERT_KEY_RE = re.compile(r"[^a-z0-9]+")


def expert_persona_key(name: str) -> str:
    slug = _EXPERT_KEY_RE.sub("_", name.strip().casefold()).strip("_")
    return slug or "expert"

DEFAULT_EXPERT_SPECS: list[dict[str, str]] = [
    {
        "name": "Finansiell analytiker",
        "description": "Bedömer lönsamhet, skuldsättning och kassaflöde.",
        "kompetensomrade": "Finansiell analys",
        "radgivningsstil": "Saklig och siffror-driven",
        "yrkesbakgrund": "15 år på investmentbank och CFO-advisory",
        "professionell_anekdot": "Har sett två förvärv kollapsa på working capital-missar i Q4.",
    },
    {
        "name": "Jurist",
        "description": "Granskar avtal, ägarstruktur och regulatoriska risker.",
        "kompetensomrade": "Legal risk",
        "radgivningsstil": "Försiktig och detaljorienterad",
        "yrkesbakgrund": "M&A-jurist på affärsjuristbyrå",
        "professionell_anekdot": "Flaggade en dold optionspool som halverade effektivt enterprise value.",
    },
    {
        "name": "Marknadsanalytiker",
        "description": "Värderar marknadsposition, konkurrens och tillväxt.",
        "kompetensomrade": "Marknadsposition",
        "radgivningsstil": "Nyfiken och konkurrensinriktad",
        "yrkesbakgrund": "Strategikonsult och marknadschef i scale-up",
        "professionell_anekdot": "Upptäckte att 'marknadsledande' bara gällde en nisch på 8 % av omsättningen.",
    },
    {
        "name": "Integrationsriskbedömare",
        "description": "Bedömer kultur, IT och operativ integrationsrisk.",
        "kompetensomrade": "Integrationsrisk",
        "radgivningsstil": "Praktisk och erfarenhetsbaserad",
        "yrkesbakgrund": "PMO-lead för post-merger integrationer",
        "professionell_anekdot": "Ett ERP-byte tog 18 månader längre än plan — kundbasen tappade förtroende under tiden.",
    },
]


def _expert_persona_id(name: str) -> str:
    return f"exp_{expert_persona_key(name)}"


def _profile_from_spec(spec: dict[str, str]) -> dict:
    profile = EditablePersona(
        name=spec["name"],
        initials=persona_initials(spec["name"]),
        yrke=spec["yrkesbakgrund"],
        kompetensomrade=spec["kompetensomrade"],
        radgivningsstil=spec["radgivningsstil"],
        yrkesbakgrund=spec["yrkesbakgrund"],
        professionell_anekdot=spec["professionell_anekdot"],
        beskrivning=spec["description"],
    )
    return profile.model_dump()


async def ensure_default_expert_personas(
    session: AsyncSession,
    *,
    customer_id: int | None = None,
) -> list[Persona]:
    """Idempotently seed the four default DD experts as Persona rows."""
    cid = customer_id if customer_id is not None else await bolag_demo_customer_id(session)
    created: list[Persona] = []
    for spec in DEFAULT_EXPERT_SPECS:
        persona_id = _expert_persona_id(spec["name"])
        existing = await session.get(Persona, persona_id)
        if existing is not None:
            continue
        row = Persona(
            id=persona_id,
            customer_id=cid,
            kind="expert",
            name=spec["name"],
            age=None,
            occ=spec["yrkesbakgrund"],
            district="—",
            quote=spec["description"],
            origin="manuell",
            profile=_profile_from_spec(spec),
            updated_at=utcnow(),
        )
        session.add(row)
        created.append(row)
    if created:
        await session.flush()
    return created
