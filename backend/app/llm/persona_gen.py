"""Build prompts and call LLM for persona profiles."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import generate_editable_persona
from app.locality import load_norrkoping_brief
from app.schemas.domain import EditablePersona, GeneratedPersonaOut
from app.serializers import persona_initials
from app.services.district_context import area_block_for_name
from app.services.persona_catalog import LEAN_LABEL


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


FIELD_GUIDE = """
Fält att fylla i (svenska strängar, korta och konkreta):
- name: för- och efternamn (svenskt eller vanligt i Sverige)
- initials: två bokstäver
- age: ålder som sträng (siffra)
- ort: stadsdel/ort
- yrke: yrke
- utbildning, livssituation, lutning, sakfragor, fortroende, ton, sprak, medievanor, parti, valdeltagande
""".strip()


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


async def llm_persona_from_slot(
    slot: SlotPlan,
    free_text: str = "",
    *,
    session: AsyncSession | None = None,
) -> GeneratedPersonaOut:
    area_block = ""
    if session is not None:
        area_block = await area_block_for_name(session, slot.district)
    user = f"""Skapa en trovärdig Norrköpingspersona.

Demografiska krav (följ dessa):
- Ålder ca {slot.age} (spann: {slot.age_bucket})
- Ort/stadsdel: {slot.district}
- Yrke: {slot.occ}
- Politisk lutning: {slot.lean_label}

Extra önskemål från användaren:
{free_text or "(inga)"}

{FIELD_GUIDE}
"""
    profile = await generate_editable_persona(
        [
            {
                "role": "system",
                "content": (
                    "Du skapar politiska testpersonas för Opinionssimulator. "
                    "Svara endast med det strukturerade objektet.\n\n"
                    f"Lokal kontext:\n{_local_context(area_block)}"
                ),
            },
            {"role": "user", "content": user},
        ]
    )
    # Enforce slot constraints that the UI recipe sampled
    profile.age = str(slot.age)
    profile.ort = slot.district or profile.ort
    profile.yrke = slot.occ or profile.yrke
    profile.lutning = slot.lean_label or profile.lutning
    if not profile.initials or profile.initials == "--":
        profile.initials = persona_initials(profile.name)
    return profile_to_generated(profile, slot)


async def llm_personas_from_description(
    free_text: str,
    count: int = 3,
    demografi: dict[str, str] | None = None,
    *,
    session: AsyncSession | None = None,
) -> list[EditablePersona]:
    area_block = ""
    if session is not None and demografi and demografi.get("ort"):
        area_block = await area_block_for_name(session, demografi["ort"])
    demo_block = ""
    if demografi:
        demo_block = "Fasta demografiska fält:\n" + "\n".join(
            f"- {k}: {v}" for k, v in demografi.items() if v
        )
    user = f"""Generera {count} distinkta kandidatpersonas.

Beskrivning:
{free_text or "(ingen fritext)"}

{demo_block}

{FIELD_GUIDE}

Returnera EN persona (vi anropar dig {count} gånger). Variera namn och detaljer.
"""
    out: list[EditablePersona] = []
    for i in range(count):
        profile = await generate_editable_persona(
            [
                {
                    "role": "system",
                    "content": (
                        "Du skapar politiska testpersonas för Opinionssimulator. "
                        f"Detta är kandidat {i + 1} av {count}.\n\n"
                        f"Lokal kontext:\n{_local_context(area_block)}"
                    ),
                },
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
