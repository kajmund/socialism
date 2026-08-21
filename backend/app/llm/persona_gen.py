"""Build prompts and call LLM for persona profiles."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import generate_editable_persona
from app.llm.persona_anecdote import llm_persona_anecdote
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
        age_bucket=slot.age_bucket if slot else "",
        lean=lean,
        lean_label=slot.lean_label if slot else LEAN_LABEL.get(lean, lean),
        trait=trait,
        quote=trait,
        profile=profile,
    )


def _local_context(area_block: str = "") -> str:
    """Local grounding from the active configuration's ort catalog only."""
    return area_block.strip()


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
    fixed_name: str | None = None,
    previous_personas: tuple[str, ...] = (),
    previous_anecdotes: tuple[str, ...] = (),
    prompts: dict[str, str] | None = None,
    include_anecdote: bool = True,
) -> GeneratedPersonaOut:
    _ = free_text, taken_surnames, previous_personas
    if prompts is None:
        if session is None:
            raise RuntimeError("session or prompts is required for persona generation")
        prompts = await require_active_prompts(session)

    locked = (fixed_name or "").strip()
    kon = slot.profile_fields.get("kön", "")
    profile = EditablePersona(
        name=locked or "—",
        initials=persona_initials(locked) if locked else "--",
        age=str(slot.age),
        kön=kon,
        ort=slot.district,
        yrke=slot.occ,
        lutning=slot.lean_label,
    )
    apply_slot_to_profile(profile, slot)
    if locked:
        profile.name = locked
        profile.initials = persona_initials(locked)
    if include_anecdote:
        profile.anekdot = await llm_persona_anecdote(
            profile,
            session=session,
            previous_anecdotes=previous_anecdotes,
            prompts=prompts,
        )
    else:
        profile.anekdot = "—"
    return profile_to_generated(profile, slot)


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
        prompts = await require_active_prompts(session)
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
