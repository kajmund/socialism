from fastapi import APIRouter, Depends, HTTPException, Query
from random import Random
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Persona, PersonaMessage, Population, PopulationMember
from app.database.session import get_session
from app.llm.chat import reply_as_persona
from app.llm.persona_gen import llm_personas_from_description
from app.schemas.domain import (
    ChatMode,
    DistGroup,
    DistRow,
    EditablePersona,
    LibraryPersona,
    PersonaChatRequest,
    PersonaChatResponse,
    PersonaCreate,
    PersonaDetail,
    PersonaGenerateRequest,
    PersonaGenerateResponse,
    PersonaMessageOut,
    PersonaUpdate,
    PopulationRecipe,
)
from app.serializers import (
    blank_profile,
    format_date,
    persona_initials,
    profile_from_dict,
    serialize_library_persona,
    serialize_persona_detail,
    slug_id,
    utcnow,
)
from app.services.district_context import area_block_for_name
from app.services.population_generate import stub_persona

router = APIRouter(prefix="/personas", tags=["personas"])


async def _population_names_for_persona(
    session: AsyncSession,
    persona_id: str,
) -> list[str]:
    result = await session.execute(
        select(Population.name)
        .join(PopulationMember, PopulationMember.population_id == Population.id)
        .where(PopulationMember.persona_id == persona_id)
        .order_by(Population.name)
    )
    return list(result.scalars().all())


async def _get_persona(session: AsyncSession, persona_id: str) -> Persona:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona


def _serialize_message(row: PersonaMessage) -> PersonaMessageOut:
    return PersonaMessageOut(
        id=row.id,
        mode=row.mode,  # type: ignore[arg-type]
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        created_at=format_date(row.created_at) if row.created_at else "",
    )


def _stub_candidates(body: PersonaGenerateRequest) -> list[EditablePersona]:
    recipe = PopulationRecipe(
        size=body.count,
        entryMode="manual",
        freeText=body.freeText,
        dist={
            "age": DistGroup(
                label="Ålder",
                rows=[
                    DistRow(k="ung", l="Ung", v=30),
                    DistRow(k="medel", l="Medel", v=40),
                    DistRow(k="aldre", l="Äldre", v=30),
                ],
            ),
            "district": DistGroup(
                label="Ort",
                rows=[
                    DistRow(k="centrum", l="Centrum", v=50),
                    DistRow(k="ovriga", l="Övriga", v=50),
                ],
            ),
            "occupation": DistGroup(
                label="Yrke",
                rows=[
                    DistRow(k="vard", l="Vård", v=50),
                    DistRow(k="ovrigt", l="Övrigt", v=50),
                ],
            ),
            "leaning": DistGroup(
                label="Lutning",
                rows=[
                    DistRow(k="vanster", l="V", v=20),
                    DistRow(k="mvanster", l="MV", v=20),
                    DistRow(k="mitt", l="M", v=20),
                    DistRow(k="mhoger", l="MH", v=20),
                    DistRow(k="hoger", l="H", v=20),
                ],
            ),
        },
        seed=secrets.randbits(16),
    )
    rng = Random(recipe.seed)
    out: list[EditablePersona] = []
    for _ in range(body.count):
        generated = stub_persona(recipe, rng)
        profile = generated.profile
        if body.demografi:
            for key, value in body.demografi.items():
                if value and hasattr(profile, key):
                    setattr(profile, key, value)
        if body.freeText and body.mode == "beskrivning":
            profile.ton = profile.ton or body.freeText[:120]
        out.append(profile)
    return out


@router.get("", response_model=list[LibraryPersona])
async def list_personas(
    q: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[LibraryPersona]:
    stmt = select(Persona).order_by(Persona.updated_at.desc())
    if origin:
        stmt = stmt.where(Persona.origin == origin)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Persona.name.ilike(like)
            | Persona.occ.ilike(like)
            | Persona.district.ilike(like)
            | Persona.quote.ilike(like)
        )
    result = await session.execute(stmt)
    personas = list(result.scalars().all())
    out: list[LibraryPersona] = []
    for persona in personas:
        pops = await _population_names_for_persona(session, persona.id)
        out.append(serialize_library_persona(persona, pops))
    return out


@router.post("/generate", response_model=PersonaGenerateResponse)
async def generate_personas(
    body: PersonaGenerateRequest,
    session: AsyncSession = Depends(get_session),
) -> PersonaGenerateResponse:
    if settings.persona_generator == "stub":
        return PersonaGenerateResponse(candidates=_stub_candidates(body))
    if not settings.uses_llm_generator():
        raise HTTPException(
            status_code=503,
            detail="PERSONA_GENERATOR must be deepseek or stub",
        )
    demografi = body.demografi if body.mode == "demografi" else None
    candidates = await llm_personas_from_description(
        free_text=body.freeText,
        count=body.count,
        demografi=demografi,
        session=session,
    )
    return PersonaGenerateResponse(candidates=candidates)


@router.get("/{persona_id}", response_model=PersonaDetail)
async def get_persona(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
) -> PersonaDetail:
    persona = await _get_persona(session, persona_id)
    pops = await _population_names_for_persona(session, persona.id)
    return serialize_persona_detail(persona, pops)


@router.post("", response_model=PersonaDetail, status_code=201)
async def create_persona(
    body: PersonaCreate,
    session: AsyncSession = Depends(get_session),
) -> PersonaDetail:
    persona_id = body.id or slug_id(body.name)
    existing = await session.get(Persona, persona_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Persona id already exists")

    profile = body.profile or EditablePersona(
        name=body.name,
        initials=persona_initials(body.name),
        age=str(body.age),
        ort=body.district,
        yrke=body.occ,
    )
    persona = Persona(
        id=persona_id,
        name=body.name,
        age=body.age,
        occ=body.occ,
        district=body.district,
        quote=body.quote,
        origin=body.origin,
        profile=profile.model_dump(),
        updated_at=utcnow(),
    )
    session.add(persona)
    await session.commit()
    await session.refresh(persona)
    return serialize_persona_detail(persona, [])


@router.put("/{persona_id}", response_model=PersonaDetail)
async def update_persona(
    persona_id: str,
    body: PersonaUpdate,
    session: AsyncSession = Depends(get_session),
) -> PersonaDetail:
    persona = await _get_persona(session, persona_id)
    data = body.model_dump(exclude_unset=True)
    profile = data.pop("profile", None)
    for key, value in data.items():
        setattr(persona, key, value)
    if profile is not None:
        persona.profile = profile
    persona.updated_at = utcnow()
    await session.commit()
    await session.refresh(persona)
    pops = await _population_names_for_persona(session, persona.id)
    return serialize_persona_detail(persona, pops)


@router.post("/{persona_id}/duplicate", response_model=PersonaDetail, status_code=201)
async def duplicate_persona(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
) -> PersonaDetail:
    source = await _get_persona(session, persona_id)
    new_id = slug_id(source.name)
    while await session.get(Persona, new_id) is not None:
        new_id = slug_id(source.name)
    persona = Persona(
        id=new_id,
        name=f"{source.name} (kopia)",
        age=source.age,
        occ=source.occ,
        district=source.district,
        quote=source.quote,
        origin=source.origin,
        profile=dict(source.profile or blank_profile(source.name).model_dump()),
        updated_at=utcnow(),
    )
    session.add(persona)
    await session.commit()
    await session.refresh(persona)
    return serialize_persona_detail(persona, [])


@router.get("/{persona_id}/messages", response_model=list[PersonaMessageOut])
async def list_messages(
    persona_id: str,
    mode: ChatMode = Query(default="interview"),
    session: AsyncSession = Depends(get_session),
) -> list[PersonaMessageOut]:
    await _get_persona(session, persona_id)
    result = await session.execute(
        select(PersonaMessage)
        .where(PersonaMessage.persona_id == persona_id, PersonaMessage.mode == mode)
        .order_by(PersonaMessage.id.asc())
    )
    return [_serialize_message(row) for row in result.scalars().all()]


@router.post("/{persona_id}/chat", response_model=PersonaChatResponse)
async def chat_with_persona(
    persona_id: str,
    body: PersonaChatRequest,
    session: AsyncSession = Depends(get_session),
) -> PersonaChatResponse:
    persona = await _get_persona(session, persona_id)
    profile = profile_from_dict(persona.profile, persona.name)

    history_rows = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.mode == body.mode,
        )
        .order_by(PersonaMessage.id.asc())
    )
    history = [(row.role, row.content) for row in history_rows.scalars().all()]

    area_block = await area_block_for_name(session, profile.ort or persona.district)
    reply = await reply_as_persona(
        profile,
        body.mode,
        history,
        body.message,
        area_block=area_block,
    )

    user_row = PersonaMessage(
        persona_id=persona_id,
        mode=body.mode,
        role="user",
        content=body.message,
        created_at=utcnow(),
    )
    assistant_row = PersonaMessage(
        persona_id=persona_id,
        mode=body.mode,
        role="assistant",
        content=reply,
        created_at=utcnow(),
    )
    session.add(user_row)
    session.add(assistant_row)
    await session.commit()
    await session.refresh(user_row)
    await session.refresh(assistant_row)

    all_rows = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.mode == body.mode,
        )
        .order_by(PersonaMessage.id.asc())
    )
    messages = [_serialize_message(row) for row in all_rows.scalars().all()]
    return PersonaChatResponse(reply=reply, messages=messages)


@router.delete("/{persona_id}/messages", status_code=204)
async def clear_messages(
    persona_id: str,
    mode: ChatMode = Query(default="interview"),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _get_persona(session, persona_id)
    result = await session.execute(
        select(PersonaMessage).where(
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.mode == mode,
        )
    )
    for row in result.scalars().all():
        await session.delete(row)
    await session.commit()


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    persona = await _get_persona(session, persona_id)
    result = await session.execute(
        select(PopulationMember)
        .options(selectinload(PopulationMember.population))
        .where(PopulationMember.persona_id == persona_id)
    )
    members = list(result.scalars().all())
    populations = {member.population for member in members if member.population is not None}
    for member in members:
        await session.delete(member)
    await session.delete(persona)
    await session.flush()
    for population in populations:
        count = await session.execute(
            select(func.count())
            .select_from(PopulationMember)
            .where(PopulationMember.population_id == population.id)
        )
        population.size = int(count.scalar_one())
        population.updated_at = utcnow()
    await session.commit()
