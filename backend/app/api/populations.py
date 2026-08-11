from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Persona, Population, PopulationMember, Run
from app.database.session import get_session
from app.schemas.domain import (
    PopulationCreate,
    PopulationDetail,
    PopulationGenerateRequest,
    PopulationGenerateResponse,
    PopulationMemberCreate,
    PopulationMemberOut,
    PopulationSummary,
    PopulationUpdate,
)
from app.serializers import (
    serialize_member,
    serialize_population_detail,
    serialize_population_summary,
    utcnow,
)
from app.services import population_generate as gen
from app.services.population_generation_store import pop_generation
from app.services.population_persist import (
    member_row,
    members_from_generation,
    reconcile_population_metadata,
)
from app.services.population_fingerprint import infer_slots_from_profile

router = APIRouter(prefix="/populations", tags=["populations"])


async def _run_count(session: AsyncSession, population_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(Run).where(Run.population_id == population_id)
    )
    return int(result.scalar_one())


async def _get_population(session: AsyncSession, population_id: int) -> Population:
    result = await session.execute(
        select(Population)
        .options(selectinload(Population.members))
        .where(Population.id == population_id)
    )
    population = result.scalar_one_or_none()
    if population is None:
        raise HTTPException(status_code=404, detail="Population not found")
    return population


def _member_from_create(
    population_id: int,
    body: PopulationMemberCreate,
) -> PopulationMember:
    return member_row(population_id, body)


async def _prepare_member_create(
    session: AsyncSession,
    population: Population,
    body: PopulationMemberCreate,
) -> PopulationMemberCreate:
    if body.age_bucket and body.lean_key and body.district_key:
        return body
    dist = (population.recipe or {}).get("dist") or {}
    profile = None
    if body.persona_id:
        persona = await session.get(Persona, body.persona_id)
        if persona is not None:
            profile = persona.profile
    inferred = infer_slots_from_profile(
        age=body.age,
        district=body.district,
        profile=profile,
        dist=dist,
    )
    return PopulationMemberCreate(
        persona_id=body.persona_id,
        name=body.name,
        initials=body.initials,
        age=body.age,
        occ=body.occ,
        district=body.district,
        trait=body.trait,
        age_bucket=body.age_bucket or inferred.age_bucket,
        lean_key=body.lean_key or inferred.lean_key,
        district_key=body.district_key or inferred.district_key,
    )


async def _members_from_generation(
    session: AsyncSession,
    generation_id: str,
    keep_keys: list[str] | None,
    extra_members: list[PopulationMemberCreate],
) -> tuple[list[PopulationMemberCreate], list[list[int]], dict]:
    try:
        return await members_from_generation(
            session, generation_id, keep_keys, extra_members
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg.lower() or "expired" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg) from exc


@router.get("", response_model=list[PopulationSummary])
async def list_populations(
    session: AsyncSession = Depends(get_session),
) -> list[PopulationSummary]:
    result = await session.execute(select(Population).order_by(Population.updated_at.desc()))
    populations = list(result.scalars().all())
    out: list[PopulationSummary] = []
    for population in populations:
        out.append(
            serialize_population_summary(population, await _run_count(session, population.id))
        )
    return out


@router.post("/generate", response_model=PopulationGenerateResponse)
async def generate_population(
    body: PopulationGenerateRequest,
    session: AsyncSession = Depends(get_session),
) -> PopulationGenerateResponse:
    ids = list(body.include_persona_ids)
    for cand in body.existing:
        if cand.source == "library" and cand.persona_id:
            ids.append(cand.persona_id)
    try:
        library = await gen.load_library_personas(session, ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = await gen.run_generate(body, library, session=session)
    await session.commit()
    return response


@router.get("/{population_id}", response_model=PopulationDetail)
async def get_population(
    population_id: int,
    session: AsyncSession = Depends(get_session),
) -> PopulationDetail:
    population = await _get_population(session, population_id)
    return serialize_population_detail(
        population,
        await _run_count(session, population.id),
        list(population.members),
    )


@router.post("", response_model=PopulationDetail, status_code=201)
async def create_population(
    body: PopulationCreate,
    session: AsyncSession = Depends(get_session),
) -> PopulationDetail:
    existing = await session.execute(select(Population).where(Population.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Population name already exists")

    members = list(body.members)
    fingerprint = body.fingerprint
    recipe = body.recipe
    if body.generation_id:
        members, fingerprint, recipe = await _members_from_generation(
            session,
            body.generation_id,
            body.keep_keys,
            body.members,
        )

    population = Population(
        name=body.name,
        size=len(members),
        versions=1,
        fingerprint=fingerprint,
        fingerprint_inferred=not bool(body.generation_id),
        recipe=recipe,
        updated_at=utcnow(),
    )
    session.add(population)
    await session.flush()
    for member in members:
        session.add(_member_from_create(population.id, member))
    await session.commit()
    if body.generation_id:
        await pop_generation(session, body.generation_id)
        await session.commit()
    population = await _get_population(session, population.id)
    return serialize_population_detail(population, 0, list(population.members))


@router.put("/{population_id}", response_model=PopulationDetail)
async def update_population(
    population_id: int,
    body: PopulationUpdate,
    session: AsyncSession = Depends(get_session),
) -> PopulationDetail:
    population = await _get_population(session, population_id)
    data = body.model_dump(exclude_unset=True)
    members = data.pop("members", None)
    bump = data.pop("bump_version", False)
    generation_id = data.pop("generation_id", None)
    keep_keys = data.pop("keep_keys", None)

    if "name" in data and data["name"] != population.name:
        clash = await session.execute(
            select(Population).where(
                Population.name == data["name"],
                Population.id != population_id,
            )
        )
        if clash.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Population name already exists")

    if not generation_id and ("fingerprint" in data or "recipe" in data):
        raise HTTPException(
            status_code=400,
            detail="Recipe and fingerprint are read-only; regenerate to change them",
        )

    if generation_id:
        extras = (
            [PopulationMemberCreate(**m) for m in members]
            if members is not None
            else []
        )
        built, fingerprint, recipe = await _members_from_generation(
            session,
            generation_id,
            keep_keys,
            extras,
        )
        for existing_member in list(population.members):
            await session.delete(existing_member)
        await session.flush()
        for member in built:
            session.add(_member_from_create(population.id, member))
        population.size = len(built)
        population.fingerprint = fingerprint
        population.fingerprint_inferred = False
        population.recipe = recipe
        data.pop("fingerprint", None)
        data.pop("recipe", None)
    elif members is not None:
        for existing_member in list(population.members):
            await session.delete(existing_member)
        await session.flush()
        for member in members:
            prepared = await _prepare_member_create(
                session,
                population,
                PopulationMemberCreate(**member),
            )
            session.add(_member_from_create(population.id, prepared))
        await session.refresh(population, attribute_names=["members"])
        await reconcile_population_metadata(population)

    for key, value in data.items():
        setattr(population, key, value)
    if bump:
        population.versions += 1
    population.updated_at = utcnow()
    await session.commit()
    if generation_id:
        await pop_generation(session, generation_id)
        await session.commit()
    population = await _get_population(session, population_id)
    return serialize_population_detail(
        population,
        await _run_count(session, population.id),
        list(population.members),
    )


@router.delete("/{population_id}", status_code=204)
async def delete_population(
    population_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    population = await _get_population(session, population_id)
    run_count = await _run_count(session, population_id)
    if run_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete population that has runs",
        )
    await session.delete(population)
    await session.commit()


@router.post("/{population_id}/duplicate", response_model=PopulationDetail, status_code=201)
async def duplicate_population(
    population_id: int,
    session: AsyncSession = Depends(get_session),
) -> PopulationDetail:
    source = await _get_population(session, population_id)
    base_name = f"{source.name} (kopia)"
    name = base_name
    suffix = 2
    while True:
        clash = await session.execute(select(Population).where(Population.name == name))
        if clash.scalar_one_or_none() is None:
            break
        name = f"{base_name} {suffix}"
        suffix += 1

    population = Population(
        name=name,
        size=source.size,
        versions=1,
        fingerprint=list(source.fingerprint or []),
        fingerprint_inferred=source.fingerprint_inferred,
        recipe=dict(source.recipe or {}),
        updated_at=utcnow(),
    )
    session.add(population)
    await session.flush()
    for member in source.members:
        session.add(
            PopulationMember(
                population_id=population.id,
                persona_id=member.persona_id,
                name=member.name,
                initials=member.initials,
                age=member.age,
                occ=member.occ,
                district=member.district,
                trait=member.trait,
                age_bucket=member.age_bucket,
                lean_key=member.lean_key,
                district_key=member.district_key,
            )
        )
    await session.commit()
    population = await _get_population(session, population.id)
    return serialize_population_detail(population, 0, list(population.members))


@router.post(
    "/{population_id}/members",
    response_model=PopulationMemberOut,
    status_code=201,
)
async def add_member(
    population_id: int,
    body: PopulationMemberCreate,
    session: AsyncSession = Depends(get_session),
) -> PopulationMemberOut:
    population = await _get_population(session, population_id)
    if body.persona_id:
        persona = await session.get(Persona, body.persona_id)
        if persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        existing = await session.execute(
            select(PopulationMember).where(
                PopulationMember.population_id == population_id,
                PopulationMember.persona_id == body.persona_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Persona already in population")
    prepared = await _prepare_member_create(session, population, body)
    member = _member_from_create(population.id, prepared)
    session.add(member)
    await session.flush()
    session.expire_all()
    population = await _get_population(session, population_id)
    await reconcile_population_metadata(population)
    population.updated_at = utcnow()
    await session.commit()
    await session.refresh(member)
    return serialize_member(member)


@router.delete("/{population_id}/members/{member_id}", status_code=204)
async def remove_member(
    population_id: int,
    member_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    population = await _get_population(session, population_id)
    result = await session.execute(
        select(PopulationMember).where(
            PopulationMember.population_id == population_id,
            PopulationMember.id == member_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    await session.delete(member)
    await session.flush()
    session.expire_all()
    population = await _get_population(session, population_id)
    await reconcile_population_metadata(population)
    population.updated_at = utcnow()
    await session.commit()
