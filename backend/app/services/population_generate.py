"""Server-side population generation (stub or OpenAI)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from random import Random

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Persona
from app.llm.persona_gen import SlotPlan, apply_slot_to_profile, llm_persona_from_slot
from app.schemas.domain import (
    DistGroup,
    EditablePersona,
    GeneratedPersonaOut,
    GenerationCandidate,
    PopulationGenerateRequest,
    PopulationGenerateResponse,
    PopulationRecipe,
)
from app.serializers import persona_initials
from app.services.persona_catalog import (
    DISTRICT_LABEL,
    JOB_BY_CAT,
    LASTN,
    LEAN_LABEL,
    NAMES_F,
    NAMES_M,
    TRAIT_BY_LEAN,
    WRITING_TRAITS,
)

LibraryPersonaRow = tuple[str, int, str, str, str]

# Re-export for older imports
__all__ = [
    "DISTRICT_LABEL",
    "JOB_BY_CAT",
    "LEAN_LABEL",
    "TRAIT_BY_LEAN",
    "clear_generations",
    "get_generation",
    "pop_generation",
    "put_generation",
    "fingerprint_from_dist",
    "stub_persona",
    "library_candidate",
    "load_library_personas",
    "run_generate",
    "sample_slot",
]


@dataclass
class StoredGeneration:
    recipe: PopulationRecipe
    fingerprint: list[list[int]]
    candidates: list[GenerationCandidate] = field(default_factory=list)


_GENERATIONS: dict[str, StoredGeneration] = {}


def clear_generations() -> None:
    _GENERATIONS.clear()


def get_generation(generation_id: str) -> StoredGeneration | None:
    return _GENERATIONS.get(generation_id)


def pop_generation(generation_id: str) -> StoredGeneration | None:
    return _GENERATIONS.pop(generation_id, None)


def put_generation(generation_id: str, stored: StoredGeneration) -> None:
    _GENERATIONS[generation_id] = stored


async def load_library_personas(
    session: AsyncSession,
    ids: list[str],
) -> dict[str, LibraryPersonaRow]:
    """Load library personas by id. Raises ValueError if any id is missing."""
    unique = list(dict.fromkeys(ids))
    if not unique:
        return {}
    result = await session.execute(select(Persona).where(Persona.id.in_(unique)))
    library: dict[str, LibraryPersonaRow] = {}
    for persona in result.scalars().all():
        library[persona.id] = (
            persona.name,
            persona.age,
            persona.occ,
            persona.district,
            persona.quote,
        )
    missing = [pid for pid in unique if pid not in library]
    if missing:
        raise ValueError(f"Persona not found: {missing[0]}")
    return library


def fingerprint_from_dist(dist: dict[str, DistGroup]) -> list[list[int]]:
    age_group = dist.get("age")
    age = [r.v for r in age_group.rows] if age_group else [33, 34, 33]

    lean_group = dist.get("leaning")
    lean_rows = lean_group.rows if lean_group else []
    left = sum(r.v for r in lean_rows if _lean_bucket(r) == "left")
    mid = sum(r.v for r in lean_rows if _lean_bucket(r) == "mid")
    right = sum(r.v for r in lean_rows if _lean_bucket(r) == "right")
    lean = [left, mid, right]

    district_group = dist.get("district")
    d_rows = district_group.rows if district_group else []
    centrum = sum(r.v for r in d_rows if _is_centrum_row(r))
    ovriga = sum(r.v for r in d_rows if _is_ovriga_row(r))
    middle = max(0, 100 - centrum - ovriga)
    return [age, lean, [centrum, middle, ovriga]]


def _norm_token(value: str) -> str:
    return (
        value.lower()
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace(" ", "_")
        .replace("-", "_")
    )


def _lean_bucket(row) -> str:
    """Map a leaning row to left/mid/right for the 3-bucket fingerprint."""
    key = _norm_token(row.k)
    label = _norm_token(row.l)
    # Legacy recipe keys
    if key in {"vanster", "mvanster"} or "vanster" in label:
        return "left"
    if key in {"mhoger", "hoger"} or "hoger" in label:
        return "right"
    if key == "mitt" or label == "mitt":
        return "mid"
    # "mitt-vanster" / "mitt_vanster" already caught by vanster; mitt-höger by hoger
    return "mid"


def _is_centrum_row(row) -> bool:
    key = _norm_token(row.k)
    label = _norm_token(row.l)
    return key == "centrum" or label == "centrum"


def _is_ovriga_row(row) -> bool:
    key = _norm_token(row.k)
    label = _norm_token(row.l)
    return key in {"ovriga", "ovrig"} or label in {"ovriga", "ovrig"}


def _weighted_pick(rng: Random, rows: list) -> str:
    total = sum(r.v for r in rows) or 1
    x = rng.random() * total
    for row in rows:
        if x < row.v:
            return row.k
        x -= row.v
    return rows[0].k


def _row_by_key(rows: list, key: str):
    for row in rows:
        if row.k == key:
            return row
    return rows[0] if rows else None


def _resolve_label(rows: list, key: str, fallback_map: dict[str, str]) -> str:
    """Prefer the recipe row label so catalog edits flow through generation."""
    row = _row_by_key(rows, key) if rows else None
    if row is not None and getattr(row, "l", None):
        return row.l
    return fallback_map.get(key, key)


def _trait_for_lean(lean_key: str, lean_label: str) -> str:
    if lean_key in TRAIT_BY_LEAN:
        return TRAIT_BY_LEAN[lean_key]
    token = _norm_token(lean_label)
    if "vanster" in token and "mitt" not in token:
        return TRAIT_BY_LEAN["vanster"]
    if "vanster" in token:
        return TRAIT_BY_LEAN["mvanster"]
    if "hoger" in token and "mitt" not in token:
        return TRAIT_BY_LEAN["hoger"]
    if "hoger" in token:
        return TRAIT_BY_LEAN["mhoger"]
    return TRAIT_BY_LEAN.get("mitt", "")


def _candidate_key() -> str:
    return f"tmp_{secrets.token_hex(4)}"


# Recipe dist group key → EditablePersona field (labels sampled into profile).
# kön is sampled separately via _sample_kon (normalized labels + fallback).
_DIST_PROFILE_FIELDS: dict[str, str] = {
    "district": "ort",
    "occupation": "yrke",
    "education": "utbildning",
    "leaning": "lutning",
    "media": "medievanor",
    "livssituation": "livssituation",
    "parti": "parti",
    "valdeltagande": "valdeltagande",
    "sakfragor": "sakfragor",
    "fortroende": "fortroende",
    "ton": "ton",
    "sprak": "sprak",
}

_KON_FEMALE = "Kvinna"
_KON_MALE = "Man"
_KON_NONBINARY = "Icke-binär"


def _norm_kon(label: str) -> str:
    token = _norm_token(label)
    if token in {"kvinna", "female", "woman", "f"} or "kvinna" in token:
        return _KON_FEMALE
    if token in {"man", "male", "m"} or token.startswith("man"):
        return _KON_MALE
    if "icke" in token or "nonbinary" in token or "non_binary" in token:
        return _KON_NONBINARY
    return label.strip() or _KON_FEMALE


def _sample_kon(dist: dict, rng: Random) -> str:
    group = dist.get("kön")
    if group is not None and group.rows:
        picked = _weighted_pick(rng, group.rows)
        return _norm_kon(_resolve_label(group.rows, picked, {}))
    return _KON_FEMALE if rng.random() < 0.5 else _KON_MALE


def _first_name_for_kon(kon: str, rng: Random) -> str:
    if kon == _KON_FEMALE:
        return rng.choice(NAMES_F)
    if kon == _KON_MALE:
        return rng.choice(NAMES_M)
    return rng.choice(NAMES_F if rng.random() < 0.5 else NAMES_M)


def surname_from_name(name: str) -> str:
    parts = name.strip().split()
    return parts[-1].casefold() if parts else ""


def surnames_from_candidates(candidates: list[GenerationCandidate]) -> set[str]:
    used: set[str] = set()
    for cand in candidates:
        persona = cand.persona
        if persona is None or not persona.name.strip():
            continue
        sur = surname_from_name(persona.name)
        if sur:
            used.add(sur)
    return used


def validate_surname_uniqueness(candidates: list[GenerationCandidate]) -> list[str]:
    """Return warning lines for duplicate surnames within a population."""
    by_surname: dict[str, list[str]] = {}
    for cand in candidates:
        persona = cand.persona
        if persona is None or not persona.name.strip():
            continue
        sur = surname_from_name(persona.name)
        if not sur:
            continue
        by_surname.setdefault(sur, []).append(persona.name)
    warnings: list[str] = []
    for sur, names in sorted(by_surname.items()):
        if len(names) > 1:
            warnings.append(
                f"Efternamn «{names[0].split()[-1]}» förekommer {len(names)} gånger: {names!r}"
            )
    return warnings


def _pick_stub_surname(rng: Random, used: set[str]) -> tuple[str, bool]:
    available = [s for s in LASTN if surname_from_name(s) not in used]
    if available:
        return rng.choice(available), False
    return rng.choice(LASTN), True


def _sample_profile_fields(dist: dict, rng: Random) -> dict[str, str]:
    fields: dict[str, str] = {}
    for group_key, profile_key in _DIST_PROFILE_FIELDS.items():
        group = dist.get(group_key)
        if group is None or not group.rows:
            continue
        picked = _weighted_pick(rng, group.rows)
        label = _resolve_label(group.rows, picked, {})
        if label:
            fields[profile_key] = label
    return fields


def _pick_writing_trait(
    occ_key: str,
    used_by_occ: dict[str, set[str]],
    rng: Random,
) -> str:
    used = used_by_occ.setdefault(occ_key, set())
    available = [trait for trait in WRITING_TRAITS if trait not in used]
    if not available:
        available = list(WRITING_TRAITS)
    choice = rng.choice(available)
    used.add(choice)
    return choice


def _writing_traits_for_slots(slots: list[SlotPlan], rng: Random) -> list[str]:
    used_by_occ: dict[str, set[str]] = {}
    return [_pick_writing_trait(slot.occ_key, used_by_occ, rng) for slot in slots]


def sample_slot(recipe: PopulationRecipe, rng: Random) -> SlotPlan:
    dist = recipe.dist
    age_rows = dist["age"].rows if "age" in dist else []
    age_bucket = _weighted_pick(rng, age_rows) if age_rows else "medel"
    if age_bucket == "ung":
        age = 20 + rng.randint(0, 14)
    elif age_bucket == "aldre":
        age = 60 + rng.randint(0, 19)
    else:
        age = 35 + rng.randint(0, 24)

    district_rows = dist["district"].rows if "district" in dist else []
    district_key = _weighted_pick(rng, district_rows) if district_rows else "centrum"
    occ_rows = dist["occupation"].rows if "occupation" in dist else []
    occ_key = _weighted_pick(rng, occ_rows) if occ_rows else "ovrigt"
    lean_rows = dist["leaning"].rows if "leaning" in dist else []
    lean = _weighted_pick(rng, lean_rows) if lean_rows else "mitt"
    lean_label = _resolve_label(lean_rows, lean, LEAN_LABEL)
    # Sample kön before other profile fields so fallback RNG is consumed once.
    kon = _sample_kon(dist, rng)
    profile_fields = _sample_profile_fields(dist, rng)
    # Keep core slot fields authoritative for denormalized GeneratedPersonaOut.
    profile_fields["ort"] = _resolve_label(district_rows, district_key, DISTRICT_LABEL)
    profile_fields["yrke"] = _resolve_label(occ_rows, occ_key, JOB_BY_CAT)
    profile_fields["lutning"] = lean_label
    profile_fields["kön"] = kon

    return SlotPlan(
        age=age,
        age_bucket=age_bucket,
        district_key=district_key,
        district=profile_fields["ort"],
        occ_key=occ_key,
        occ=profile_fields["yrke"],
        lean=lean,
        lean_label=lean_label,
        profile_fields=profile_fields,
    )


def stub_persona(
    recipe: PopulationRecipe,
    rng: Random,
    *,
    used_surnames: set[str] | None = None,
    slot: SlotPlan | None = None,
    writing_trait: str | None = None,
) -> GeneratedPersonaOut:
    slot = slot or sample_slot(recipe, rng)
    kon = slot.profile_fields.get("kön") or _sample_kon(recipe.dist, rng)
    first = _first_name_for_kon(kon, rng)
    if used_surnames is None:
        last = rng.choice(LASTN)
    else:
        last, _forced = _pick_stub_surname(rng, used_surnames)
        sur = surname_from_name(last)
        if sur:
            used_surnames.add(sur)
    name = f"{first} {last}"
    initials = persona_initials(name)
    voice = writing_trait or _trait_for_lean(slot.lean, slot.lean_label)
    profile = EditablePersona(
        name=name,
        initials=initials,
        age=str(slot.age),
        kön=kon,
        ort=slot.district,
        yrke=slot.occ,
        lutning=slot.lean_label,
        ton=voice,
    )
    apply_slot_to_profile(profile, slot)
    if writing_trait:
        profile.ton = writing_trait
    trait = writing_trait or profile.ton or profile.sakfragor or _trait_for_lean(
        slot.lean, slot.lean_label
    )
    return GeneratedPersonaOut(
        name=name,
        initials=initials,
        age=slot.age,
        occ=slot.occ,
        district=slot.district,
        occ_key=slot.occ_key,
        district_key=slot.district_key,
        lean=slot.lean,
        lean_label=slot.lean_label,
        trait=trait,
        quote=trait,
        profile=profile,
    )


def library_candidate(
    persona_id: str,
    name: str,
    age: int,
    occ: str,
    district: str,
    quote: str,
) -> GenerationCandidate:
    initials = persona_initials(name)
    profile = EditablePersona(
        name=name,
        initials=initials,
        age=str(age),
        ort=district,
        yrke=occ,
        ton=quote,
    )
    return GenerationCandidate(
        key=_candidate_key(),
        source="library",
        persona_id=persona_id,
        persona=GeneratedPersonaOut(
            name=name,
            initials=initials,
            age=age,
            occ=occ,
            district=district,
            occ_key="",
            district_key="",
            lean="mitt",
            lean_label="Mitt",
            trait=quote,
            quote=quote,
            profile=profile,
        ),
    )


async def _make_generated_batch(
    recipe: PopulationRecipe,
    rng: Random,
    count: int,
    *,
    session: AsyncSession | None = None,
    used_surnames: set[str] | None = None,
) -> tuple[list[GeneratedPersonaOut], list[str]]:
    if count <= 0:
        return [], []
    warnings: list[str] = []
    surnames = used_surnames if used_surnames is not None else set()

    if settings.persona_generator == "stub":
        slots = [sample_slot(recipe, rng) for _ in range(count)]
        writing_traits = _writing_traits_for_slots(slots, rng)
        personas: list[GeneratedPersonaOut] = []
        for slot, voice in zip(slots, writing_traits, strict=True):
            prior = set(surnames)
            persona = stub_persona(
                recipe,
                rng,
                used_surnames=surnames,
                slot=slot,
                writing_trait=voice,
            )
            personas.append(persona)
            sur = surname_from_name(persona.name)
            if sur and sur in prior:
                warnings.append(
                    f"Stub: efternamn «{persona.name.split()[-1]}» kolliderar "
                    f"({len(LASTN)} unika i katalogen)"
                )
        return personas, warnings

    if not settings.uses_llm_generator():
        raise HTTPException(
            status_code=503,
            detail="PERSONA_GENERATOR must be deepseek or stub",
        )
    slots = [sample_slot(recipe, rng) for _ in range(count)]
    writing_traits = _writing_traits_for_slots(slots, rng)
    personas: list[GeneratedPersonaOut] = []
    previous_personas: list[str] = []
    for slot, voice in zip(slots, writing_traits, strict=True):
        persona, slot_warnings = await _llm_persona_unique_surname(
            slot,
            free_text=recipe.freeText,
            session=session,
            used_surnames=surnames,
            writing_trait=voice,
            previous_personas=tuple(previous_personas),
        )
        personas.append(persona)
        warnings.extend(slot_warnings)
        previous_personas.append(
            f"{persona.name} | yrke: {persona.occ} | röst: {persona.trait[:80]}"
        )
    return personas, warnings


async def _llm_persona_unique_surname(
    slot: SlotPlan,
    *,
    free_text: str,
    session: AsyncSession | None,
    used_surnames: set[str],
    writing_trait: str | None = None,
    previous_personas: tuple[str, ...] = (),
) -> tuple[GeneratedPersonaOut, list[str]]:
    warnings: list[str] = []
    persona: GeneratedPersonaOut | None = None
    for _attempt in range(3):
        persona = await llm_persona_from_slot(
            slot,
            free_text=free_text,
            session=session,
            taken_surnames=frozenset(used_surnames),
            writing_trait=writing_trait,
            previous_personas=previous_personas,
        )
        sur = surname_from_name(persona.name)
        if not sur or sur not in used_surnames:
            if sur:
                used_surnames.add(sur)
            return persona, warnings
    assert persona is not None
    sur = surname_from_name(persona.name)
    if sur and sur in used_surnames:
        last = persona.name.split()[-1] if persona.name.split() else persona.name
        warnings.append(
            f"Efternamn «{last}» kolliderar efter 3 försök: {persona.name!r}"
        )
    if sur:
        used_surnames.add(sur)
    return persona, warnings


async def run_generate(
    body: PopulationGenerateRequest,
    library_personas: dict[str, tuple[str, int, str, str, str]],
    *,
    session: AsyncSession | None = None,
) -> PopulationGenerateResponse:
    """library_personas: id -> (name, age, occ, district, quote)."""
    recipe = body.recipe
    rng = Random(recipe.seed if recipe.seed is not None else secrets.randbits(32))

    existing = list(body.existing)
    if not existing and body.generation_id:
        stored = get_generation(body.generation_id)
        if stored is not None:
            existing = list(stored.candidates)

    include_ids = list(body.include_persona_ids)
    present_library = {c.persona_id for c in existing if c.source == "library" and c.persona_id}
    for persona_id in include_ids:
        if persona_id in present_library:
            continue
        row = library_personas.get(persona_id)
        if row is None:
            continue
        existing.append(library_candidate(persona_id, *row))
        present_library.add(persona_id)

    used_surnames = surnames_from_candidates(existing)
    gen_warnings: list[str] = []

    if body.replace_keys:
        replace_set = set(body.replace_keys)
        replace_count = sum(
            1 for c in existing if c.key in replace_set and c.source == "generated"
        )
        personas, batch_warnings = await _make_generated_batch(
            recipe,
            rng,
            replace_count,
            session=session,
            used_surnames=used_surnames,
        )
        gen_warnings.extend(batch_warnings)
        persona_iter = iter(personas)
        candidates: list[GenerationCandidate] = []
        for cand in existing:
            if cand.key in replace_set and cand.source == "generated":
                candidates.append(
                    GenerationCandidate(
                        key=cand.key,
                        source="generated",
                        persona_id=None,
                        persona=next(persona_iter),
                    )
                )
            else:
                candidates.append(cand)
    elif body.mode == "append":
        candidates = list(existing)
        need = max(0, recipe.size - len(candidates))
        personas, batch_warnings = await _make_generated_batch(
            recipe,
            rng,
            need,
            session=session,
            used_surnames=used_surnames,
        )
        gen_warnings.extend(batch_warnings)
        for persona in personas:
            candidates.append(
                GenerationCandidate(
                    key=_candidate_key(),
                    source="generated",
                    persona_id=None,
                    persona=persona,
                )
            )
    else:
        kept = [c for c in existing if c.source == "library"]
        need = max(0, recipe.size - len(kept))
        candidates = list(kept)
        personas, batch_warnings = await _make_generated_batch(
            recipe,
            rng,
            need,
            session=session,
            used_surnames=used_surnames,
        )
        gen_warnings.extend(batch_warnings)
        for persona in personas:
            candidates.append(
                GenerationCandidate(
                    key=_candidate_key(),
                    source="generated",
                    persona_id=None,
                    persona=persona,
                )
            )

    generation_id = body.generation_id or f"gen_{secrets.token_hex(8)}"
    fingerprint = fingerprint_from_dist(recipe.dist)
    put_generation(
        generation_id,
        StoredGeneration(recipe=recipe, fingerprint=fingerprint, candidates=candidates),
    )
    gen_warnings = list(dict.fromkeys(gen_warnings + validate_surname_uniqueness(candidates)))
    return PopulationGenerateResponse(
        generation_id=generation_id,
        fingerprint=fingerprint,
        candidates=candidates,
        warnings=gen_warnings,
    )
