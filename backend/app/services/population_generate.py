"""Server-side population generation (stub or OpenAI)."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from random import Random

from fastapi import HTTPException

from app.config import settings
from app.llm.persona_gen import SlotPlan, llm_persona_from_slot
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
)

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


def fingerprint_from_dist(dist: dict[str, DistGroup]) -> list[list[int]]:
    age_group = dist.get("age")
    age = [r.v for r in age_group.rows] if age_group else [33, 34, 33]

    lean_group = dist.get("leaning")
    lean_rows = lean_group.rows if lean_group else []
    lean_map = {r.k: r.v for r in lean_rows}
    lean = [
        lean_map.get("vanster", 0) + lean_map.get("mvanster", 0),
        lean_map.get("mitt", 0),
        lean_map.get("mhoger", 0) + lean_map.get("hoger", 0),
    ]

    district_group = dist.get("district")
    d_map = {r.k: r.v for r in district_group.rows} if district_group else {}
    centrum = d_map.get("centrum", 0)
    ovriga = d_map.get("ovriga", 0)
    middle = max(0, 100 - centrum - ovriga)
    return [age, lean, [centrum, middle, ovriga]]


def _weighted_pick(rng: Random, rows: list) -> str:
    total = sum(r.v for r in rows) or 1
    x = rng.random() * total
    for row in rows:
        if x < row.v:
            return row.k
        x -= row.v
    return rows[0].k


def _candidate_key() -> str:
    return f"tmp_{secrets.token_hex(4)}"


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

    return SlotPlan(
        age=age,
        age_bucket=age_bucket,
        district_key=district_key,
        district=DISTRICT_LABEL.get(district_key, district_key),
        occ_key=occ_key,
        occ=JOB_BY_CAT.get(occ_key, occ_key),
        lean=lean,
        lean_label=LEAN_LABEL.get(lean, lean),
    )


def stub_persona(recipe: PopulationRecipe, rng: Random) -> GeneratedPersonaOut:
    slot = sample_slot(recipe, rng)
    is_f = rng.random() < 0.5
    first = rng.choice(NAMES_F if is_f else NAMES_M)
    last = rng.choice(LASTN)
    name = f"{first} {last}"
    trait = TRAIT_BY_LEAN.get(slot.lean, "")
    initials = persona_initials(name)
    profile = EditablePersona(
        name=name,
        initials=initials,
        age=str(slot.age),
        ort=slot.district,
        yrke=slot.occ,
        lutning=slot.lean_label,
        ton=trait,
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
) -> list[GeneratedPersonaOut]:
    if count <= 0:
        return []
    if settings.persona_generator == "stub" or not settings.deepseek_api_key:
        return [stub_persona(recipe, rng) for _ in range(count)]
    if not settings.uses_llm_generator():
        raise HTTPException(
            status_code=503,
            detail="DeepSeek is not configured (set DEEPSEEK_API_KEY or PERSONA_GENERATOR=stub)",
        )
    # Sample slots first so Random stays single-threaded, then fan out LLM calls.
    slots = [sample_slot(recipe, rng) for _ in range(count)]
    return list(
        await asyncio.gather(
            *[llm_persona_from_slot(slot, free_text=recipe.freeText) for slot in slots]
        )
    )


async def run_generate(
    body: PopulationGenerateRequest,
    library_personas: dict[str, tuple[str, int, str, str, str]],
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

    if body.replace_keys:
        replace_set = set(body.replace_keys)
        replace_count = sum(
            1 for c in existing if c.key in replace_set and c.source == "generated"
        )
        personas = await _make_generated_batch(recipe, rng, replace_count)
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
        for persona in await _make_generated_batch(recipe, rng, need):
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
        for persona in await _make_generated_batch(recipe, rng, need):
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
    return PopulationGenerateResponse(
        generation_id=generation_id,
        fingerprint=fingerprint,
        candidates=candidates,
    )
