"""Default DD expert personas (seeded from panel_expert_profiles catalog)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund, Persona
from app.schemas.domain import EditablePersona
from app.serializers import persona_initials, utcnow
from app.services.dd.expert_keys import expert_persona_id
from app.services.expert_tools import default_expert_tools
from app.services.kund_store import ensure_default_kunder
from app.services.panel.expert_profiles_store import (
    ensure_expert_profile_defaults,
    get_expert_profiles,
)
from app.services.panel.spinndoctor_profile import SPINNDOCTOR_KEY

# Seed data for PanelExpertProfile (and MODULE_REGISTRY.expert_defaults_provider).
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


def _profile_from_fields(
    *,
    name: str,
    description: str,
    kompetensomrade: str,
    radgivningsstil: str,
    yrkesbakgrund: str,
    professionell_anekdot: str,
) -> dict:
    profile = EditablePersona(
        name=name,
        initials=persona_initials(name),
        yrke=yrkesbakgrund,
        kompetensomrade=kompetensomrade,
        radgivningsstil=radgivningsstil,
        yrkesbakgrund=yrkesbakgrund,
        professionell_anekdot=professionell_anekdot,
        beskrivning=description,
    )
    return profile.model_dump()


async def ensure_default_expert_personas(
    session: AsyncSession,
    *,
    customer_id: int | None = None,
) -> list[Persona]:
    """Idempotently seed default DD experts as Persona rows from the catalog store.

    ``customer_id=None`` seeds every kund (startup / admin list-all).
    """
    if customer_id is None:
        await ensure_default_kunder(session)
        ids = [
            int(row)
            for row in (await session.execute(select(Kund.id).order_by(Kund.id))).scalars()
        ]
        created: list[Persona] = []
        for cid in ids:
            created.extend(await ensure_default_expert_personas(session, customer_id=cid))
        return created

    cid = customer_id
    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    profiles = [
        row
        for row in await get_expert_profiles(session, "dd", customer_id=cid)
        if row.key != SPINNDOCTOR_KEY
    ]
    if not profiles:
        raise RuntimeError(
            f"No active panel expert profiles for module 'dd' customer_id={cid}"
        )

    created: list[Persona] = []
    for profile in profiles:
        persona_id = expert_persona_id(cid, profile.key)
        existing = await session.get(Persona, persona_id)
        if existing is not None:
            if existing.tools is None:
                existing.tools = default_expert_tools()
            continue
        row = Persona(
            id=persona_id,
            customer_id=cid,
            kind="expert",
            name=profile.name,
            age=None,
            occ=profile.yrkesbakgrund,
            district="—",
            quote=profile.description,
            origin="manuell",
            profile=_profile_from_fields(
                name=profile.name,
                description=profile.description,
                kompetensomrade=profile.kompetensomrade,
                radgivningsstil=profile.radgivningsstil,
                yrkesbakgrund=profile.yrkesbakgrund,
                professionell_anekdot=profile.professionell_anekdot,
            ),
            tools=default_expert_tools(),
            updated_at=utcnow(),
        )
        session.add(row)
        created.append(row)
    if created:
        await session.flush()
    return created
