"""Server-side population generation (stub or OpenAI)."""

from __future__ import annotations

import asyncio
import secrets
from random import Random

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Persona
from app.llm.persona_anecdote import llm_persona_anecdote, stub_persona_anecdote
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
)
from app.services.population_fingerprint import (
    compare_target_vs_achieved,
    compare_target_vs_candidates,
    fingerprint_from_candidates,
    fingerprint_from_dist,
    infer_slots_from_profile,
    slots_from_persona,
)
from app.services.population_generation_store import (
    StoredGeneration,
    clear_generations,
    get_generation,
    pop_generation,
    put_generation,
)
from app.services.prompt_store import require_active_prompts

LibraryPersonaRow = tuple[str, int, str, str, str]

# Re-export for older imports

__all__ = [
    "DISTRICT_LABEL",
    "JOB_BY_CAT",
    "LEAN_LABEL",
    "StoredGeneration",
    "clear_generations",
    "fingerprint_from_dist",
    "get_generation",
    "library_candidate",
    "load_library_personas",
    "pop_generation",
    "put_generation",
    "run_generate",
    "sample_slot",
    "stub_persona",
]


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


def _norm_token(value: str) -> str:
    return (
        value.lower()
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace(" ", "_")
        .replace("-", "_")
    )


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


def _filled_profile_text(value: str) -> str:
    text = value.strip()
    return "" if text in ("", "—") else text


def _slot_ton(slot: SlotPlan) -> str:
    return _filled_profile_text(slot.profile_fields.get("ton", ""))


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
    profile = EditablePersona(
        name=name,
        initials=initials,
        age=str(slot.age),
        kön=kon,
        ort=slot.district,
        yrke=slot.occ,
        lutning=slot.lean_label,
    )
    apply_slot_to_profile(profile, slot)
    profile.anekdot = stub_persona_anecdote(profile, rng)
    trait = _filled_profile_text(profile.ton) or _filled_profile_text(profile.sakfragor)
    return GeneratedPersonaOut(
        name=name,
        initials=initials,
        age=slot.age,
        occ=slot.occ,
        district=slot.district,
        occ_key=slot.occ_key,
        district_key=slot.district_key,
        age_bucket=slot.age_bucket,
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


def _assign_unique_names(
    slots: list[SlotPlan],
    rng: Random,
    used_surnames: set[str],
    *,
    used_full_names: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Pre-assign catalog names; resolve full-name and surname clashes."""
    names: list[str] = []
    warnings: list[str] = []
    full_names = used_full_names if used_full_names is not None else set()
    for slot in slots:
        kon = slot.profile_fields.get("kön") or _KON_FEMALE
        name: str | None = None
        for _attempt in range(24):
            first = _first_name_for_kon(kon, rng)
            last, forced = _pick_stub_surname(rng, used_surnames)
            candidate = f"{first} {last}"
            if candidate.casefold() in full_names:
                continue
            sur = surname_from_name(last)
            if sur:
                used_surnames.add(sur)
            if forced:
                warnings.append(
                    f"Efternamn «{last}» återanvänds ({len(LASTN)} unika i katalogen)"
                )
            name = candidate
            break
        if name is None:
            first = _first_name_for_kon(kon, rng)
            last, _forced = _pick_stub_surname(rng, used_surnames)
            sur = surname_from_name(last)
            if sur:
                used_surnames.add(sur)
            n = 2
            base = f"{first} {last}"
            name = base
            while name.casefold() in full_names:
                name = f"{base} ({n})"
                n += 1
            warnings.append(f"Namn «{base}» disambiguerades till «{name}»")
        full_names.add(name.casefold())
        names.append(name)
    return names, warnings


def _sibling_persona_lines(
    names: list[str],
    slots: list[SlotPlan],
) -> tuple[str, ...]:
    lines: list[str] = []
    for name, slot in zip(names, slots, strict=True):
        ton = _slot_ton(slot)
        if ton:
            lines.append(f"{name} | yrke: {slot.occ} | röst: {ton[:80]}")
        else:
            lines.append(f"{name} | yrke: {slot.occ}")
    return tuple(lines)


async def _load_existing_persona_name_sets(
    session: AsyncSession | None,
) -> tuple[set[str], set[str]]:
    """Return (full_names_casefold, surnames_casefold) already in the library."""
    if session is None:
        return set(), set()
    result = await session.execute(select(Persona.name))
    full: set[str] = set()
    surnames: set[str] = set()
    for name in result.scalars().all():
        if not name or not str(name).strip():
            continue
        text = str(name).strip()
        full.add(text.casefold())
        sur = surname_from_name(text)
        if sur:
            surnames.add(sur)
    return full, surnames


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
    existing_full, existing_surnames = await _load_existing_persona_name_sets(session)
    surnames |= existing_surnames
    used_full = set(existing_full)

    if settings.persona_generator == "stub":
        slots = [sample_slot(recipe, rng) for _ in range(count)]
        names, name_warnings = _assign_unique_names(
            slots,
            rng,
            surnames,
            used_full_names=used_full,
        )
        warnings.extend(name_warnings)
        personas: list[GeneratedPersonaOut] = []
        for slot, name in zip(slots, names, strict=True):
            persona = stub_persona(
                recipe,
                rng,
                used_surnames=None,
                slot=slot,
            )
            # Keep pre-assigned unique name (stub_persona picks its own otherwise).
            persona = GeneratedPersonaOut(
                **{
                    **persona.model_dump(),
                    "name": name,
                    "initials": persona_initials(name),
                    "profile": persona.profile.model_copy(
                        update={"name": name, "initials": persona_initials(name)}
                    ),
                }
            )
            personas.append(persona)
        return personas, warnings

    if not settings.uses_llm_generator():
        raise HTTPException(
            status_code=503,
            detail="PERSONA_GENERATOR must be deepseek or stub",
        )
    slots = [sample_slot(recipe, rng) for _ in range(count)]
    names, name_warnings = _assign_unique_names(
        slots,
        rng,
        surnames,
        used_full_names=used_full,
    )
    warnings.extend(name_warnings)
    sibling_lines = _sibling_persona_lines(names, slots)
    prompts = await require_active_prompts(session) if session is not None else None
    concurrency = settings.persona_generate_concurrency
    sem = asyncio.Semaphore(concurrency)

    async def _profile_one(index: int) -> GeneratedPersonaOut:
        others = tuple(line for i, line in enumerate(sibling_lines) if i != index)
        async with sem:
            return await llm_persona_from_slot(
                slots[index],
                session=session,
                fixed_name=names[index],
                previous_personas=others,
                prompts=prompts,
                include_anecdote=False,
            )

    personas = list(await asyncio.gather(*[_profile_one(i) for i in range(count)]))

    previous_anecdotes: list[str] = []
    for wave_start in range(0, count, concurrency):
        wave_indices = list(range(wave_start, min(wave_start + concurrency, count)))
        wave_prev = tuple(previous_anecdotes)

        async def _anecdote_one(
            index: int,
            prev: tuple[str, ...] = wave_prev,
        ) -> tuple[int, str]:
            async with sem:
                text = await llm_persona_anecdote(
                    personas[index].profile,
                    session=session,
                    previous_anecdotes=prev,
                    prompts=prompts,
                )
                return index, text

        wave_results = await asyncio.gather(*[_anecdote_one(i) for i in wave_indices])
        for index, text in sorted(wave_results, key=lambda item: item[0]):
            personas[index].profile.anekdot = text
            personas[index] = GeneratedPersonaOut(
                **{
                    **personas[index].model_dump(),
                    "profile": personas[index].profile,
                }
            )
            cleaned = text.strip()
            if cleaned in ("", "—"):
                warnings.append(
                    f"Anekdot saknas för {personas[index].name} "
                    "(LLM-svar ogiltigt efter retries)."
                )
            else:
                previous_anecdotes.append(cleaned)

    return personas, warnings


async def run_generate(
    body: PopulationGenerateRequest,
    library_personas: dict[str, tuple[str, int, str, str, str]],
    *,
    session: AsyncSession | None = None,
) -> PopulationGenerateResponse:
    """library_personas: id -> (name, age, occ, district, quote)."""
    if session is None:
        raise ValueError("session is required for population generation staging")

    recipe = body.recipe
    rng = Random(recipe.seed if recipe.seed is not None else secrets.randbits(32))

    existing = list(body.existing)
    if not existing and body.generation_id:
        stored = await get_generation(session, body.generation_id)
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
    target_fingerprint = fingerprint_from_dist(recipe.dist)
    achieved_fingerprint = fingerprint_from_candidates(candidates, recipe.dist)
    qa_warnings = compare_target_vs_candidates(recipe.dist, candidates)
    await put_generation(
        session,
        generation_id,
        StoredGeneration(
            recipe=recipe,
            fingerprint=achieved_fingerprint,
            candidates=candidates,
            qa_warnings=qa_warnings,
        ),
    )
    gen_warnings = list(dict.fromkeys(gen_warnings + validate_surname_uniqueness(candidates)))
    return PopulationGenerateResponse(
        generation_id=generation_id,
        fingerprint=achieved_fingerprint,
        candidates=candidates,
        warnings=gen_warnings,
        qa_warnings=qa_warnings,
        target_fingerprint=target_fingerprint,
    )
