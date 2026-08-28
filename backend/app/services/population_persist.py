"""Persist generated population candidates as personas + population members."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Persona, Population, PopulationMember
from app.schemas.domain import PopulationMemberCreate, PopulationRecipe
from app.serializers import slug_id, utcnow
from app.services.kund_store import default_os_customer_id
from app.services.population_fingerprint import (
    compare_target_vs_achieved,
    fingerprint_from_members,
    infer_slots_from_profile,
    slots_from_persona,
)
from app.services.population_generation_store import get_generation, pop_generation

_DEFAULT_POPULATION_NAME = "Namnlös population"


def member_row(
    population_id: int,
    body: PopulationMemberCreate,
    *,
    member_kind: str = "persona",
) -> PopulationMember:
    return PopulationMember(
        population_id=population_id,
        persona_id=body.persona_id,
        kind=member_kind,
        name=body.name,
        initials=body.initials,
        age=body.age,
        occ=body.occ,
        district=body.district,
        trait=body.trait,
        age_bucket=body.age_bucket,
        lean_key=body.lean_key,
        district_key=body.district_key,
    )


def _member_create_from_candidate(
    candidate,
    *,
    persona_id: str | None,
    recipe_dist: dict,
    population_kind: str = "persona",
) -> PopulationMemberCreate:
    persona = candidate.persona
    slots = slots_from_persona(persona)
    if (
        population_kind == "persona"
        and candidate.source == "library"
        and persona_id
    ):
        inferred = infer_slots_from_profile(
            age=persona.age,
            district=persona.district,
            profile=persona.profile.model_dump(),
            dist=recipe_dist,
        )
        slots = inferred
    return PopulationMemberCreate(
        persona_id=persona_id,
        name=persona.name,
        initials=persona.initials,
        age=persona.age,
        occ=persona.occ,
        district=persona.district,
        trait=persona.trait,
        age_bucket=slots.age_bucket,
        lean_key=slots.lean_key,
        district_key=slots.district_key,
    )


async def reconcile_population_metadata(population: Population) -> list[str]:
    dist = (population.recipe or {}).get("dist") or {}
    members = list(population.members)
    population.fingerprint = fingerprint_from_members(members, dist)
    population.size = len(members)
    return compare_target_vs_achieved(dist, members)


async def members_from_generation(
    session: AsyncSession,
    generation_id: str,
    keep_keys: list[str] | None = None,
    extra_members: list[PopulationMemberCreate] | None = None,
    *,
    population_kind: str = "persona",
) -> tuple[list[PopulationMemberCreate], list[list[int]], dict]:
    stored = await get_generation(session, generation_id)
    if stored is None:
        raise ValueError("Generation not found or expired")

    keep = set(keep_keys) if keep_keys is not None else None
    members: list[PopulationMemberCreate] = []
    seen_persona_ids: set[str] = set()
    recipe_dist = stored.recipe.dist

    for candidate in stored.candidates:
        if keep is not None and candidate.key not in keep:
            continue
        persona = candidate.persona
        persona_id = candidate.persona_id
        if candidate.source == "generated":
            persona_id = slug_id(persona.name)
            while await session.get(Persona, persona_id) is not None:
                persona_id = slug_id(persona.name)
            customer_id = await default_os_customer_id(session)
            session.add(
                Persona(
                    id=persona_id,
                    customer_id=customer_id,
                    name=persona.name,
                    age=persona.age,
                    occ=persona.occ,
                    district=persona.district,
                    quote=persona.quote or persona.trait,
                    origin="population",
                    profile=persona.profile.model_dump(),
                    updated_at=utcnow(),
                )
            )
        elif persona_id:
            existing = await session.get(Persona, persona_id)
            if existing is None:
                raise ValueError(f"Persona not found: {persona_id}")

        if persona_id:
            seen_persona_ids.add(persona_id)
        members.append(
            _member_create_from_candidate(
                candidate,
                persona_id=persona_id,
                recipe_dist=recipe_dist,
                population_kind=population_kind,
            )
        )

    for extra in extra_members or []:
        if extra.persona_id and extra.persona_id in seen_persona_ids:
            continue
        if extra.persona_id:
            seen_persona_ids.add(extra.persona_id)
        members.append(extra)

    return members, stored.fingerprint, stored.recipe.model_dump()


async def allocate_unique_population_name(
    session: AsyncSession,
    desired: str,
    *,
    exclude_id: int | None = None,
) -> str:
    """Return desired name, or «Name (2)», «Name (3)», … if taken."""
    base = desired.strip() or _DEFAULT_POPULATION_NAME
    candidate = base
    n = 2
    while True:
        stmt = select(Population.id).where(Population.name == candidate)
        if exclude_id is not None:
            stmt = stmt.where(Population.id != exclude_id)
        taken = (await session.execute(stmt)).scalar_one_or_none()
        if taken is None:
            return candidate
        candidate = f"{base} ({n})"
        n += 1


async def create_population_from_generation(
    session: AsyncSession,
    *,
    name: str,
    generation_id: str,
    kind: str = "persona",
) -> Population:
    unique_name = await allocate_unique_population_name(session, name)

    members, fingerprint, recipe = await members_from_generation(
        session,
        generation_id,
        population_kind=kind,
    )
    member_kind = "expert" if kind == "expert_panel" else "persona"
    population = Population(
        kind=kind,
        name=unique_name,
        size=len(members),
        versions=1,
        fingerprint=fingerprint,
        fingerprint_inferred=False,
        recipe=recipe,
        updated_at=utcnow(),
    )
    session.add(population)
    await session.flush()
    for member in members:
        session.add(member_row(population.id, member, member_kind=member_kind))
    await session.flush()
    await pop_generation(session, generation_id)
    return population


async def update_population_from_generation(
    session: AsyncSession,
    *,
    population_id: int,
    name: str,
    generation_id: str,
    recipe: PopulationRecipe | None = None,
    kind: str | None = None,
) -> Population:
    result = await session.execute(
        select(Population)
        .options(selectinload(Population.members))
        .where(Population.id == population_id)
    )
    population = result.scalar_one_or_none()
    if population is None:
        raise ValueError("Population not found")

    if name != population.name:
        population.name = await allocate_unique_population_name(
            session,
            name,
            exclude_id=population_id,
        )

    population_kind = kind or population.kind
    members, fingerprint, recipe_dump = await members_from_generation(
        session,
        generation_id,
        population_kind=population_kind,
    )
    member_kind = "expert" if population_kind == "expert_panel" else "persona"
    for existing_member in list(population.members):
        await session.delete(existing_member)
    await session.flush()
    for member in members:
        session.add(member_row(population.id, member, member_kind=member_kind))
    population.size = len(members)
    population.fingerprint = fingerprint
    population.fingerprint_inferred = False
    population.recipe = recipe.model_dump() if recipe is not None else recipe_dump
    if kind is not None:
        population.kind = kind
    population.versions += 1
    population.updated_at = utcnow()
    await session.flush()
    await pop_generation(session, generation_id)
    return population

