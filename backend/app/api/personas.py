import secrets
from random import Random

from fastapi import APIRouter, Depends, HTTPException, Query
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
    PersonaMessageDeleteResponse,
    PersonaMessageOut,
    PersonaUpdate,
    PopulationRecipe,
    SuggestedQuestionsResponse,
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
from app.services.persona_chat import (
    ChatTurnError,
    library_follow_up_questions,
    safe_library_follow_ups,
)
from app.services.population_generate import stub_persona
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.expert_tools import resolve_expert_tools
from app.services.kund_store import bolag_demo_customer_id, default_os_customer_id
from app.services.prompt_store import require_active_prompts

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
        run_id=row.run_id,
        attempt_id=row.attempt_id,
        variant_id=row.variant_id,
        through_tick_index=row.through_tick_index,
    )


def _stub_candidates(body: PersonaGenerateRequest) -> list[EditablePersona]:
    recipe = PopulationRecipe(
        size=body.count,
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
    exclude_origin: list[str] | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[LibraryPersona]:
    if kind == "expert":
        created = await ensure_default_expert_personas(session, customer_id=customer_id)
        if created:
            await session.commit()

    stmt = select(Persona).order_by(Persona.updated_at.desc())
    if customer_id is not None:
        stmt = stmt.where(Persona.customer_id == customer_id)
    if kind is not None:
        stmt = stmt.where(Persona.kind == kind)
    if origin:
        stmt = stmt.where(Persona.origin == origin)
    if exclude_origin:
        stmt = stmt.where(Persona.origin.notin_(exclude_origin))
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

    if body.profile is not None:
        profile = body.profile
    elif body.kind == "expert":
        occ = body.occ or "—"
        profile = EditablePersona(
            name=body.name,
            initials=persona_initials(body.name),
            yrke=occ,
            yrkesbakgrund=occ,
            ort=body.district,
            beskrivning=body.quote,
        )
    else:
        profile = EditablePersona(
            name=body.name,
            initials=persona_initials(body.name),
            age=str(body.age),
            ort=body.district,
            yrke=body.occ,
        )

    if body.kind == "expert":
        customer_id = body.customer_id or await bolag_demo_customer_id(session)
        occ = body.occ or profile.yrkesbakgrund or profile.yrke or "—"
        quote = body.quote or (
            profile.beskrivning if profile.beskrivning not in ("", "—") else ""
        )
    else:
        customer_id = body.customer_id or await default_os_customer_id(session)
        occ = body.occ
        quote = body.quote

    persona = Persona(
        id=persona_id,
        customer_id=customer_id,
        kind=body.kind,
        name=body.name,
        age=body.age,
        occ=occ,
        district=body.district,
        quote=quote,
        origin=body.origin,
        profile=profile.model_dump(),
        tools=resolve_expert_tools(body.tools) if body.kind == "expert" else None,
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
    tools_set = "tools" in data
    tools = data.pop("tools", None)
    for key, value in data.items():
        setattr(persona, key, value)
    if profile is not None:
        persona.profile = profile
    if tools_set:
        persona.tools = resolve_expert_tools(tools) if persona.kind == "expert" else None
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
        customer_id=source.customer_id,
        kind=source.kind,
        name=f"{source.name} (kopia)",
        age=source.age,
        occ=source.occ,
        district=source.district,
        quote=source.quote,
        origin=source.origin,
        profile=dict(source.profile or blank_profile(source.name).model_dump()),
        tools=list(source.tools) if source.tools is not None else source.tools,
        updated_at=utcnow(),
    )
    session.add(persona)
    await session.commit()
    await session.refresh(persona)
    return serialize_persona_detail(persona, [])


def _library_chat_filter(persona_id: str, mode: ChatMode):
    """Library interview/character chat — exclude run-scoped post-hoc threads."""
    return (
        PersonaMessage.persona_id == persona_id,
        PersonaMessage.mode == mode,
        PersonaMessage.run_id.is_(None),
    )


@router.get(
    "/{persona_id}/suggested-questions",
    response_model=SuggestedQuestionsResponse,
)
async def get_suggested_questions(
    persona_id: str,
    mode: ChatMode = Query(default="interview"),
    session: AsyncSession = Depends(get_session),
) -> SuggestedQuestionsResponse:
    await _get_persona(session, persona_id)
    try:
        questions = await library_follow_up_questions(
            session,
            persona_id=persona_id,
            mode=mode,
        )
    except ChatTurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return SuggestedQuestionsResponse(questions=questions)


@router.get("/{persona_id}/messages", response_model=list[PersonaMessageOut])
async def list_messages(
    persona_id: str,
    mode: ChatMode = Query(default="interview"),
    session: AsyncSession = Depends(get_session),
) -> list[PersonaMessageOut]:
    await _get_persona(session, persona_id)
    result = await session.execute(
        select(PersonaMessage)
        .where(*_library_chat_filter(persona_id, mode))
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
        .where(*_library_chat_filter(persona_id, body.mode))
        .order_by(PersonaMessage.id.asc())
    )
    history = [(row.role, row.content) for row in history_rows.scalars().all()]

    area_block = await area_block_for_name(session, profile.ort or persona.district)
    prompts = await require_active_prompts(session)
    reply = await reply_as_persona(
        profile,
        body.mode,
        history,
        body.message,
        prompts=prompts,
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
        .where(*_library_chat_filter(persona_id, body.mode))
        .order_by(PersonaMessage.id.asc())
    )
    messages = [_serialize_message(row) for row in all_rows.scalars().all()]
    suggestions = await safe_library_follow_ups(
        profile,
        body.mode,
        [(row.role, row.content) for row in messages],
        prompts=prompts,
    )
    return PersonaChatResponse(reply=reply, messages=messages, suggestions=suggestions)


@router.delete("/{persona_id}/messages", status_code=204)
async def clear_messages(
    persona_id: str,
    mode: ChatMode = Query(default="interview"),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _get_persona(session, persona_id)
    result = await session.execute(
        select(PersonaMessage).where(*_library_chat_filter(persona_id, mode))
    )
    for row in result.scalars().all():
        await session.delete(row)
    await session.commit()


@router.delete(
    "/{persona_id}/messages/{message_id}",
    response_model=PersonaMessageDeleteResponse,
)
async def delete_message(
    persona_id: str,
    message_id: int,
    session: AsyncSession = Depends(get_session),
) -> PersonaMessageDeleteResponse:
    await _get_persona(session, persona_id)
    result = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.id == message_id,
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.run_id.is_(None),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Meddelande hittades inte")

    thread = await session.execute(
        select(PersonaMessage)
        .where(*_library_chat_filter(persona_id, row.mode))
        .order_by(PersonaMessage.id.asc())
    )
    rows = list(thread.scalars().all())
    idx = next((i for i, msg in enumerate(rows) if msg.id == message_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Meddelande hittades inte")

    to_delete = [rows[idx]]
    if row.role == "user" and idx + 1 < len(rows) and rows[idx + 1].role == "assistant":
        to_delete.append(rows[idx + 1])
    elif row.role == "assistant" and idx > 0 and rows[idx - 1].role == "user":
        to_delete.insert(0, rows[idx - 1])

    deleted_ids = [msg.id for msg in to_delete]
    for msg in to_delete:
        await session.delete(msg)
    await session.commit()
    return PersonaMessageDeleteResponse(deleted_ids=deleted_ids)


@router.post("/{persona_id}/messages/{message_id}/resend", response_model=PersonaChatResponse)
async def resend_message(
    persona_id: str,
    message_id: int,
    session: AsyncSession = Depends(get_session),
) -> PersonaChatResponse:
    persona = await _get_persona(session, persona_id)
    profile = profile_from_dict(persona.profile, persona.name)

    result = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.id == message_id,
            PersonaMessage.persona_id == persona_id,
            PersonaMessage.run_id.is_(None),
        )
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Meddelande hittades inte")

    all_result = await session.execute(
        select(PersonaMessage)
        .where(*_library_chat_filter(persona_id, target.mode))
        .order_by(PersonaMessage.id.asc())
    )
    all_rows = list(all_result.scalars().all())
    idx = next((i for i, row in enumerate(all_rows) if row.id == message_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Meddelande hittades inte")

    kept = all_rows[:idx]
    for row in all_rows[idx:]:
        await session.delete(row)
    await session.flush()

    area_block = await area_block_for_name(session, profile.ort or persona.district)
    prompts = await require_active_prompts(session)
    mode = target.mode

    if target.role == "user":
        history = [(row.role, row.content) for row in kept]
        user_message = target.content
        reply = await reply_as_persona(
            profile,
            mode,
            history,
            user_message,
            prompts=prompts,
            area_block=area_block,
        )
        session.add(
            PersonaMessage(
                persona_id=persona_id,
                mode=mode,
                role="user",
                content=user_message,
                created_at=utcnow(),
            )
        )
        session.add(
            PersonaMessage(
                persona_id=persona_id,
                mode=mode,
                role="assistant",
                content=reply,
                created_at=utcnow(),
            )
        )
    else:
        if not kept or kept[-1].role != "user":
            raise HTTPException(
                status_code=400,
                detail="Kan inte regenerera utan föregående användarmeddelande",
            )
        user_message = kept[-1].content
        history = [(row.role, row.content) for row in kept[:-1]]
        reply = await reply_as_persona(
            profile,
            mode,
            history,
            user_message,
            prompts=prompts,
            area_block=area_block,
        )
        session.add(
            PersonaMessage(
                persona_id=persona_id,
                mode=mode,
                role="assistant",
                content=reply,
                created_at=utcnow(),
            )
        )

    await session.commit()

    all_rows = await session.execute(
        select(PersonaMessage)
        .where(*_library_chat_filter(persona_id, mode))
        .order_by(PersonaMessage.id.asc())
    )
    messages = [_serialize_message(row) for row in all_rows.scalars().all()]
    suggestions = await safe_library_follow_ups(
        profile,
        mode,
        [(row.role, row.content) for row in messages],
        prompts=prompts,
    )
    return PersonaChatResponse(reply=reply, messages=messages, suggestions=suggestions)


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
