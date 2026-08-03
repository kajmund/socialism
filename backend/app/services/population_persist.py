"""Persist generated population candidates as personas + population members."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Persona, Population, PopulationMember
from app.schemas.domain import PopulationMemberCreate, PopulationRecipe
from app.serializers import slug_id, utcnow
from app.services import population_generate as gen


def member_row(population_id: int, body: PopulationMemberCreate) -> PopulationMember:
    return PopulationMember(
        population_id=population_id,
        persona_id=body.persona_id,
        name=body.name,
        initials=body.initials,
        age=body.age,
        occ=body.occ,
        district=body.district,
        trait=body.trait,
    )


async def members_from_generation(
    session: AsyncSession,
    generation_id: str,
    keep_keys: list[str] | None = None,
    extra_members: list[PopulationMemberCreate] | None = None,
) -> tuple[list[PopulationMemberCreate], list[list[int]], dict]:
    stored = gen.get_generation(generation_id)
    if stored is None:
        raise ValueError("Generation not found or expired")

    keep = set(keep_keys) if keep_keys is not None else None
    members: list[PopulationMemberCreate] = []
    seen_persona_ids: set[str] = set()

    for candidate in stored.candidates:
        if keep is not None and candidate.key not in keep:
            continue
        persona = candidate.persona
        persona_id = candidate.persona_id
        if candidate.source == "generated":
            persona_id = slug_id(persona.name)
            while await session.get(Persona, persona_id) is not None:
                persona_id = slug_id(persona.name)
            session.add(
                Persona(
                    id=persona_id,
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
            PopulationMemberCreate(
                persona_id=persona_id,
                name=persona.name,
                initials=persona.initials,
                age=persona.age,
                occ=persona.occ,
                district=persona.district,
                trait=persona.trait,
            )
        )

    for extra in extra_members or []:
        if extra.persona_id and extra.persona_id in seen_persona_ids:
            continue
        if extra.persona_id:
            seen_persona_ids.add(extra.persona_id)
        members.append(extra)

    return members, stored.fingerprint, stored.recipe.model_dump()


async def create_population_from_generation(
    session: AsyncSession,
    *,
    name: str,
    generation_id: str,
) -> Population:
    clash = await session.execute(select(Population).where(Population.name == name))
    if clash.scalar_one_or_none() is not None:
        raise ValueError("Population name already exists")

    members, fingerprint, recipe = await members_from_generation(session, generation_id)
    population = Population(
        name=name,
        size=len(members),
        versions=1,
        fingerprint=fingerprint,
        recipe=recipe,
        updated_at=utcnow(),
    )
    session.add(population)
    await session.flush()
    for member in members:
        session.add(member_row(population.id, member))
    await session.flush()
    gen.pop_generation(generation_id)
    return population


async def update_population_from_generation(
    session: AsyncSession,
    *,
    population_id: int,
    name: str,
    generation_id: str,
    recipe: PopulationRecipe | None = None,
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
        clash = await session.execute(
            select(Population).where(Population.name == name, Population.id != population_id)
        )
        if clash.scalar_one_or_none() is not None:
            raise ValueError("Population name already exists")
        population.name = name

    members, fingerprint, recipe_dump = await members_from_generation(session, generation_id)
    for existing_member in list(population.members):
        await session.delete(existing_member)
    await session.flush()
    for member in members:
        session.add(member_row(population.id, member))
    population.size = len(members)
    population.fingerprint = fingerprint
    population.recipe = recipe.model_dump() if recipe is not None else recipe_dump
    population.versions += 1
    population.updated_at = utcnow()
    await session.flush()
    gen.pop_generation(generation_id)
    return population
