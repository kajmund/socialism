"""Build prompts and call LLM for persona profiles."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import generate_editable_persona
from app.llm.persona_anecdote import llm_persona_anecdote
from app.locality import load_norrkoping_brief
from app.schemas.domain import EditablePersona, GeneratedPersonaOut
from app.serializers import persona_initials
from app.services.district_context import area_block_for_name
from app.services.persona_catalog import LEAN_LABEL
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts


@dataclass(frozen=True)
class SlotPlan:
    age: int
    age_bucket: str
    district_key: str
    district: str
    occ_key: str
    occ: str
    lean: str
    lean_label: str
    # EditablePersona field name → sampled catalog label (ton, parti, …).
    profile_fields: dict[str, str] = field(default_factory=dict)


def profile_to_generated(profile: EditablePersona, slot: SlotPlan | None = None) -> GeneratedPersonaOut:
    age = int("".join(ch for ch in profile.age if ch.isdigit()) or "0")
    trait = profile.ton or profile.sakfragor or ""
    lean = slot.lean if slot else "mitt"
    return GeneratedPersonaOut(
        name=profile.name,
        initials=profile.initials or persona_initials(profile.name),
        age=age if age > 0 else (slot.age if slot else 40),
        occ=profile.yrke or (slot.occ if slot else "—"),
        district=profile.ort or (slot.district if slot else "—"),
        occ_key=slot.occ_key if slot else "",
        district_key=slot.district_key if slot else "",
        lean=lean,
        lean_label=slot.lean_label if slot else LEAN_LABEL.get(lean, lean),
        trait=trait,
        quote=trait,
        profile=profile,
    )


def _local_context(area_block: str = "") -> str:
    brief = load_norrkoping_brief()
    if area_block.strip():
        return f"{brief}\n\n{area_block.strip()}"
    return brief


_PROFILE_FIELD_LABELS: dict[str, str] = {
    "kön": "Kön",
    "ort": "Ort/stadsdel",
    "yrke": "Yrke",
    "utbildning": "Utbildning",
    "livssituation": "Livssituation",
    "lutning": "Politisk lutning",
    "sakfragor": "Sakfrågor",
    "fortroende": "Förtroende",
    "ton": "Ton",
    "sprak": "Språkmönster",
    "medievanor": "Medievanor",
    "parti": "Partisympati",
    "valdeltagande": "Valdeltagande",
}


def _slot_requirement_lines(slot: SlotPlan) -> list[str]:
    lines = [
        f"- Ålder ca {slot.age} (spann: {slot.age_bucket})",
        f"- Ort/stadsdel: {slot.district}",
        f"- Yrke: {slot.occ}",
        f"- Politisk lutning: {slot.lean_label}",
    ]
    skip = {"ort", "yrke", "lutning"}
    for key, value in slot.profile_fields.items():
        if key in skip or not value:
            continue
        label = _PROFILE_FIELD_LABELS.get(key, key)
        lines.append(f"- {label}: {value}")
    return lines


def apply_slot_to_profile(profile: EditablePersona, slot: SlotPlan) -> None:
    """Overwrite profile fields with values sampled from the population recipe."""
    profile.age = str(slot.age)
    profile.ort = slot.district or profile.ort
    profile.yrke = slot.occ or profile.yrke
    profile.lutning = slot.lean_label or profile.lutning
    for key, value in slot.profile_fields.items():
        if value and hasattr(profile, key):
            setattr(profile, key, value)
    if not profile.initials or profile.initials == "--":
        profile.initials = persona_initials(profile.name)


async def llm_persona_from_slot(
    slot: SlotPlan,
    free_text: str = "",
    *,
    session: AsyncSession | None = None,
    taken_surnames: frozenset[str] | None = None,
    writing_trait: str | None = None,
    previous_personas: tuple[str, ...] = (),
    previous_anecdotes: tuple[str, ...] = (),
    prompts: dict[str, str] | None = None,
) -> GeneratedPersonaOut:
    if prompts is None:
        if session is None:
            raise RuntimeError("session or prompts is required for persona generation")
        prompts = await require_active_prompts(session, "sv")
    area_block = ""
    if session is not None:
        area_block = await area_block_for_name(session, slot.district)
    requirements = "\n".join(_slot_requirement_lines(slot))
    surname_block = ""
    if taken_surnames:
        listed = ", ".join(sorted(taken_surnames))
        surname_block = (
            f"\nEfternamn som redan används i populationen (välj ett annat): {listed}\n"
            "Varje efternamn ska vara unikt inom populationen.\n"
        )
    voice_block = ""
    if writing_trait:
        voice_block = (
            f"\nSkrivsätt / röst (följ särskilt): {writing_trait}\n"
            "Låt temperament och skrivstil skilja sig tydligt från andra med samma yrke.\n"
        )
    if previous_personas:
        prev_lines = "\n".join(f"  * {line}" for line in previous_personas[-12:])
        voice_block += (
            f"\nPersonas som redan skapats i denna population (variera röst och detaljer):\n"
            f"{prev_lines}\n"
        )
    field_guide = render_prompt(prompts, "persona.field_guide")
    user = render_prompt(
        prompts,
        "persona.from_slot.user",
        requirements=requirements,
        surname_block=surname_block,
        voice_block=voice_block,
        free_text=free_text or "(inga)",
        field_guide=field_guide,
    )
    system = render_prompt(
        prompts,
        "persona.from_slot.system",
        local_context=_local_context(area_block),
    )
    profile = await generate_editable_persona(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    apply_slot_to_profile(profile, slot)
    if writing_trait:
        profile.ton = writing_trait
    profile.anekdot = await llm_persona_anecdote(
        profile,
        session=session,
        previous_anecdotes=previous_anecdotes,
        prompts=prompts,
    )
    generated = profile_to_generated(profile, slot)
    if writing_trait:
        return GeneratedPersonaOut(
            **{
                **generated.model_dump(),
                "trait": writing_trait,
                "quote": writing_trait,
                "profile": profile,
            }
        )
    return generated


async def llm_personas_from_description(
    free_text: str,
    count: int = 3,
    demografi: dict[str, str] | None = None,
    *,
    session: AsyncSession | None = None,
    prompts: dict[str, str] | None = None,
) -> list[EditablePersona]:
    if prompts is None:
        if session is None:
            raise RuntimeError("session or prompts is required for persona generation")
        prompts = await require_active_prompts(session, "sv")
    area_block = ""
    if session is not None and demografi and demografi.get("ort"):
        area_block = await area_block_for_name(session, demografi["ort"])
    demo_block = ""
    if demografi:
        demo_block = "Fasta demografiska fält:\n" + "\n".join(
            f"- {k}: {v}" for k, v in demografi.items() if v
        )
    field_guide = render_prompt(prompts, "persona.field_guide")
    user = render_prompt(
        prompts,
        "persona.from_description.user",
        count=count,
        free_text=free_text or "(ingen fritext)",
        demo_block=demo_block,
        field_guide=field_guide,
    )
    out: list[EditablePersona] = []
    for i in range(count):
        system = render_prompt(
            prompts,
            "persona.from_description.system",
            candidate_index=i + 1,
            candidate_count=count,
            local_context=_local_context(area_block),
        )
        profile = await generate_editable_persona(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        if demografi:
            for key, value in demografi.items():
                if value and hasattr(profile, key):
                    setattr(profile, key, value)
        if not profile.initials or profile.initials == "--":
            profile.initials = persona_initials(profile.name)
        out.append(profile)
    return out
