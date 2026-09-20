import asyncio
import secrets
from random import Random
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.auth.scope import (
    assert_kund_access,
    customer_id_for_user,
    effective_customer_id,
    require_user_kund_id,
)
from app.config import settings
from app.database.models import (
    Persona,
    PersonaMessage,
    Population,
    PopulationMember,
    StoredObject,
    UserAccount,
)
from app.database.session import get_session
from app.llm.chat import build_chat_system_prompt, reply_as_persona
from app.llm.expert_gen import ExpertCandidate, llm_experts_from_underlag
from app.llm.persona_gen import llm_personas_from_description
from app.modules.registry import MODULE_REGISTRY
from app.schemas.domain import (
    ChatMode,
    EditablePersona,
    ExpertMemoryListOut,
    ExpertMemoryOut,
    ExpertMemoryUpdate,
    LibraryPersona,
    PersonaAvatarOut,
    PersonaChatRequest,
    PersonaChatResponse,
    PersonaCreate,
    PersonaDetail,
    PersonaGenerateRequest,
    PersonaGenerateResponse,
    PersonaLiveMemoryRequest,
    PersonaLiveTokenOut,
    PersonaLiveToolRequest,
    PersonaLiveToolResponse,
    PersonaMessageDeleteResponse,
    PersonaMessageOut,
    PersonaUpdate,
    SuggestedQuestionsResponse,
)
from app.serializers import (
    blank_profile,
    format_date,
    persona_avatar_url,
    persona_initials,
    profile_from_dict,
    serialize_library_persona,
    serialize_persona_detail,
    slug_id,
    utcnow,
)
from app.services.avatar_images import MAX_AVATAR_BYTES, normalize_avatar_image
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.dd.expert_keys import persona_catalog_key
from app.services.district_context import area_block_for_name
from app.services.expert_chat_evidence import (
    combine_expert_chat_context,
    reusable_expert_chat_evidence_context,
)
from app.services.expert_chat_research_tool import research_tool_handler_for_chat
from app.services.expert_tools import expert_tool_prompt_extra, resolve_chat_tools
from app.services.expertgranskning.memory import get_expert_memory, memory_belongs_to
from app.services.expertgranskning.memory_view import (
    attach_expert_labels,
    directory_experts,
    expert_directory,
    labeled_memory,
)
from app.services.gemini_live import (
    GeminiLiveProviderError,
    GeminiLiveUnavailable,
    create_gemini_live_token,
)
from app.services.kund_store import bolag_demo_customer_id, default_os_customer_id
from app.services.live_voice_context import build_live_voice_context
from app.services.live_voice_tools import live_voice_tool_specs, run_live_voice_tool
from app.services.object_storage import (
    KIND_UNDERLAG,
    ObjectStorageError,
    delete_object,
    ensure_bucket,
    get_object,
    put_object,
)
from app.services.panel.catalog_schemas import ExpertSuggestIn
from app.services.persona_chat import (
    ChatTurnError,
    expert_memory_context,
    library_follow_up_questions,
    remember_expert_chat_turn,
    safe_library_follow_ups,
)
from app.services.population_generate import (
    politik_identity_recipe,
    sample_expert_identity,
    stub_persona,
)
from app.services.prompt_store import require_active_prompts, require_prompts_for_persona
from app.services.stored_objects import get_stored_object, read_stored_bytes
from app.services.underlag_extract import ensure_underlag_extracted

router = APIRouter(prefix="/personas", tags=["personas"])
PERSONA_AVATAR_BUCKET = "persona-avatars"


def _own_underlag(row: StoredObject | None, *, customer_id: int, user_id: str) -> StoredObject:
    if (
        row is None
        or row.kind != KIND_UNDERLAG
        or row.customer_id != customer_id
        or row.owner_user_id != user_id
    ):
        raise HTTPException(status_code=404, detail="File not found")
    return row


async def _underlag_text_for_suggest(session: AsyncSession, row: StoredObject, *, module: str) -> str:
    if row.module != module:
        raise HTTPException(status_code=400, detail="Underlag module does not match")
    try:
        return await ensure_underlag_extracted(
            session,
            row,
            read_bytes=read_stored_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


async def _require_memory_expert(
    session: AsyncSession,
    persona_id: str,
    user: UserAccount,
) -> Persona:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        raise HTTPException(status_code=404, detail="Memory not found")
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
        image_sha256=row.image_sha256,
    )


def _stub_candidates(body: PersonaGenerateRequest) -> list[EditablePersona]:
    recipe = politik_identity_recipe(seed=secrets.randbits(16), size=body.count)
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
    user: UserAccount = Depends(get_current_user),
) -> list[LibraryPersona]:
    customer_id = effective_customer_id(user, customer_id)
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
    _user: UserAccount = Depends(get_current_user),
) -> PersonaGenerateResponse:
    if settings.persona_generator == "stub":
        return PersonaGenerateResponse(candidates=_stub_candidates(body))
    if not settings.uses_llm_generator():
        raise HTTPException(
            status_code=503,
            detail="PERSONA_GENERATOR must be deepseek or stub",
        )
    demografi = body.demografi if body.mode == "demografi" else None
    customer_id = await default_os_customer_id(session)
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module="politik",
        language="sv",
    )
    candidates = await llm_personas_from_description(
        free_text=body.freeText,
        count=body.count,
        demografi=demografi,
        session=session,
        prompts=prompts,
    )
    return PersonaGenerateResponse(candidates=candidates)


@router.post("/suggest-from-underlag", response_model=list[ExpertCandidate])
async def suggest_experts_from_underlag(
    body: ExpertSuggestIn,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[ExpertCandidate]:
    if body.module not in MODULE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown module {body.module!r}")
    customer_id = await customer_id_for_user(session, user)
    row = _own_underlag(
        await get_stored_object(session, body.underlag_id),
        customer_id=customer_id,
        user_id=user.id,
    )
    try:
        text = await _underlag_text_for_suggest(session, row, module=body.module)
    except HTTPException:
        # Persist failed/empty extraction status written by ensure_underlag_extracted.
        await session.commit()
        raise
    # Persist deferred extraction before the LLM call so a later failure still
    # leaves the underlag extracted for the next attempt.
    await session.commit()
    try:
        return await llm_experts_from_underlag(
            text,
            body.count,
            body.module,
            session,
            customer_id=customer_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{persona_id}", response_model=PersonaDetail)
async def get_persona(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PersonaDetail:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    pops = await _population_names_for_persona(session, persona.id)
    return serialize_persona_detail(persona, pops)


@router.post("/{persona_id}/live-token", response_model=PersonaLiveTokenOut)
async def create_persona_live_token(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PersonaLiveTokenOut:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        raise HTTPException(status_code=404, detail="Expert not found")

    profile = profile_from_dict(persona.profile, persona.name)
    prompts = await require_prompts_for_persona(session, persona)
    area_block = await area_block_for_name(session, profile.ort or persona.district)
    live_context, initial_turn = await build_live_voice_context(
        session,
        persona=persona,
        user=user,
        prompts=prompts,
    )
    allowed_tools = resolve_chat_tools(persona.tools, kind=persona.kind)
    tool_context = expert_tool_prompt_extra(prompts, allowed_tools)
    extra_system = "\n\n".join(
        part for part in (live_context, tool_context) if part.strip()
    )
    system_instruction = build_chat_system_prompt(
        profile,
        "interview",
        prompts=prompts,
        area_block=area_block,
        extra_system=extra_system,
        profile_kind="expert",
    )
    try:
        token, model, voice, expires_at = await create_gemini_live_token(
            system_instruction,
            tools=live_voice_tool_specs(persona),
        )
    except GeminiLiveUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GeminiLiveProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return PersonaLiveTokenOut(
        token=token,
        model=model,
        voice=voice,
        expires_at=expires_at,
        initial_turn=initial_turn,
    )


@router.post(
    "/{persona_id}/live-tool",
    response_model=PersonaLiveToolResponse,
)
async def run_persona_live_tool(
    persona_id: str,
    body: PersonaLiveToolRequest,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PersonaLiveToolResponse:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        raise HTTPException(status_code=404, detail="Expert not found")
    history = [(item.role, item.content, None) for item in body.history]
    try:
        result = await run_live_voice_tool(
            session,
            persona=persona,
            user=user,
            session_id=body.session_id,
            name=body.name,
            arguments=body.arguments,
            history=history,
            user_message=body.user_message,
        )
    except ValueError as exc:
        status = 403 if str(exc) == "voice_tool_not_allowed" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return PersonaLiveToolResponse(result=result)


@router.post("/{persona_id}/live-memory", status_code=202)
async def remember_persona_live_turn(
    persona_id: str,
    body: PersonaLiveMemoryRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        raise HTTPException(status_code=404, detail="Expert not found")
    background_tasks.add_task(
        remember_expert_chat_turn,
        persona,
        message=body.user_message,
        reply=body.assistant_message,
        image_sha256=None,
        session_id=body.session_id,
    )


@router.get("/{persona_id}/avatar")
async def read_persona_avatar(
    persona_id: str,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if not persona.avatar_key:
        raise HTTPException(404, "avatar_not_found")
    try:
        data, content_type = await get_object(PERSONA_AVATAR_BUCKET, persona.avatar_key)
    except ObjectStorageError as exc:
        raise HTTPException(502, "avatar_storage_error") from exc
    return Response(
        data,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{persona_id}/avatar", response_model=PersonaAvatarOut)
async def upload_persona_avatar(
    persona_id: str,
    file: UploadFile,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PersonaAvatarOut:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        raise HTTPException(422, "persona_avatar_expert_only")
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "avatar_too_large")
    data = await asyncio.to_thread(normalize_avatar_image, data)
    key = f"{persona.customer_id}/{persona.id}/{uuid4().hex}.jpg"
    old = persona.avatar_key
    try:
        await ensure_bucket(PERSONA_AVATAR_BUCKET)
        await put_object(PERSONA_AVATAR_BUCKET, key, data, "image/jpeg")
    except ObjectStorageError as exc:
        raise HTTPException(502, "avatar_storage_error") from exc
    result = await session.execute(
        update(Persona)
        .where(Persona.id == persona.id, Persona.avatar_revision == persona.avatar_revision)
        .values(avatar_key=key, avatar_revision=Persona.avatar_revision + 1)
    )
    if result.rowcount != 1:
        await session.rollback()
        await delete_object(PERSONA_AVATAR_BUCKET, key)
        raise HTTPException(409, "persona_changed")
    await session.commit()
    await session.refresh(persona)
    if old:
        await delete_object(PERSONA_AVATAR_BUCKET, old)
    return PersonaAvatarOut(avatar_url=persona_avatar_url(persona))


@router.delete("/{persona_id}/avatar", response_model=PersonaAvatarOut)
async def remove_persona_avatar(
    persona_id: str,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PersonaAvatarOut:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        raise HTTPException(422, "persona_avatar_expert_only")
    old = persona.avatar_key
    result = await session.execute(
        update(Persona)
        .where(Persona.id == persona.id, Persona.avatar_revision == persona.avatar_revision)
        .values(avatar_key=None, avatar_revision=Persona.avatar_revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "persona_changed")
    await session.commit()
    await session.refresh(persona)
    if old:
        await delete_object(PERSONA_AVATAR_BUCKET, old)
    return PersonaAvatarOut(avatar_url=None)


@router.post("", response_model=PersonaDetail, status_code=201)
async def create_persona(
    body: PersonaCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PersonaDetail:
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

    name = body.name
    age = body.age
    if body.kind == "expert":
        if body.id:
            persona_id = body.id
            if await session.get(Persona, persona_id) is not None:
                raise HTTPException(status_code=409, detail="Persona id already exists")
            display_name, sampled_age, kon = sample_expert_identity(Random(secrets.randbits(32)))
        else:
            while True:
                display_name, sampled_age, kon = sample_expert_identity(
                    Random(secrets.randbits(32))
                )
                persona_id = slug_id(display_name)
                if await session.get(Persona, persona_id) is None:
                    break
        name = display_name
        age = sampled_age
        profile.name = display_name
        profile.initials = persona_initials(display_name)
        profile.age = str(sampled_age)
        profile.kön = kon
    else:
        persona_id = body.id or slug_id(body.name)

    existing = await session.get(Persona, persona_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Persona id already exists")

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

    if user.role != "admin":
        customer_id = require_user_kund_id(user)

    persona = Persona(
        id=persona_id,
        customer_id=customer_id,
        kind=body.kind,
        name=name,
        age=age,
        occ=occ,
        district=body.district,
        quote=quote,
        origin=body.origin,
        profile=profile.model_dump(),
        tools=resolve_chat_tools(body.tools, kind=body.kind),
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
    user: UserAccount = Depends(get_current_user),
) -> PersonaDetail:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    data = body.model_dump(exclude_unset=True)
    profile = data.pop("profile", None)
    tools_set = "tools" in data
    tools = data.pop("tools", None)
    for key, value in data.items():
        setattr(persona, key, value)
    if profile is not None:
        persona.profile = profile
    if tools_set:
        persona.tools = resolve_chat_tools(tools, kind=persona.kind)
    persona.updated_at = utcnow()
    await session.commit()
    await session.refresh(persona)
    pops = await _population_names_for_persona(session, persona.id)
    return serialize_persona_detail(persona, pops)


@router.post("/{persona_id}/duplicate", response_model=PersonaDetail, status_code=201)
async def duplicate_persona(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> PersonaDetail:
    source = await _get_persona(session, persona_id)
    assert_kund_access(user, source.customer_id)
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
    user: UserAccount = Depends(get_current_user),
) -> SuggestedQuestionsResponse:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    try:
        questions = await library_follow_up_questions(
            session,
            persona_id=persona_id,
            mode=mode,
        )
    except ChatTurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return SuggestedQuestionsResponse(questions=questions)


@router.get("/{persona_id}/memories", response_model=ExpertMemoryListOut)
async def list_persona_memories(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExpertMemoryListOut:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    if persona.kind != "expert":
        return ExpertMemoryListOut(
            customer_id=persona.customer_id,
            count=0,
            memories=[],
        )
    expert_id = persona_catalog_key(persona)
    hits = await get_expert_memory().list_all(
        customer_id=persona.customer_id,
        expert_id=expert_id,
    )
    directory = await expert_directory(session, customer_id=persona.customer_id)
    memories = attach_expert_labels(hits, directory, customer_id=persona.customer_id)
    return ExpertMemoryListOut(
        customer_id=persona.customer_id,
        count=len(memories),
        memories=memories,
        experts=directory_experts(directory, customer_id=persona.customer_id),
    )


@router.delete("/{persona_id}/memories", status_code=204)
async def clear_persona_memories(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    persona = await _require_memory_expert(session, persona_id, user)
    await get_expert_memory().delete_all(
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
    )


@router.patch("/{persona_id}/memories/{memory_id}", response_model=ExpertMemoryOut)
async def update_persona_memory(
    persona_id: str,
    memory_id: str,
    body: ExpertMemoryUpdate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> ExpertMemoryOut:
    persona = await _require_memory_expert(session, persona_id, user)
    memory = get_expert_memory()
    existing = await memory.get(memory_id=memory_id)
    if existing is None or not memory_belongs_to(
        existing,
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
    ):
        raise HTTPException(status_code=404, detail="Memory not found")
    updated = await memory.update(memory_id=memory_id, text=body.text)
    return await labeled_memory(session, updated, customer_id=persona.customer_id)


@router.delete("/{persona_id}/memories/{memory_id}", status_code=204)
async def delete_persona_memory(
    persona_id: str,
    memory_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    persona = await _require_memory_expert(session, persona_id, user)
    memory = get_expert_memory()
    existing = await memory.get(memory_id=memory_id)
    if existing is None or not memory_belongs_to(
        existing,
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
    ):
        raise HTTPException(status_code=404, detail="Memory not found")
    await memory.delete(memory_id=memory_id)


@router.get("/{persona_id}/messages", response_model=list[PersonaMessageOut])
async def list_messages(
    persona_id: str,
    mode: ChatMode = Query(default="interview"),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[PersonaMessageOut]:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
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
    user: UserAccount = Depends(get_current_user),
) -> PersonaChatResponse:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    profile = profile_from_dict(persona.profile, persona.name)

    history_rows = await session.execute(
        select(PersonaMessage)
        .where(*_library_chat_filter(persona_id, body.mode))
        .order_by(PersonaMessage.id.asc())
    )
    history = [(row.role, row.content, row.image_sha256) for row in history_rows.scalars().all()]

    area_block = await area_block_for_name(session, profile.ort or persona.district)
    prompts = await require_prompts_for_persona(session, persona)
    memory_context = await expert_memory_context(
        persona, body.message, prompts, image_sha256=body.image_sha256
    )
    evidence_context = ""
    if persona.kind == "expert":
        evidence_context = await reusable_expert_chat_evidence_context(
            session,
            customer_id=persona.customer_id,
            question=body.message,
            prompts=prompts,
        )
    from app.services.actor_profiles import ActorProfileTools
    reply = await reply_as_persona(
        profile,
        body.mode,
        history,
        body.message,
        prompts=prompts,
        area_block=area_block,
        extra_system=combine_expert_chat_context(memory_context, evidence_context),
        user_image_sha256=body.image_sha256,
        profile_kind=persona.kind,
        tools=persona.tools,
        actor_tool_handler=ActorProfileTools(session, user_id=user.id, customer_id=persona.customer_id, conversation=f"expert:{persona.id}:{body.mode}") if persona.kind == "expert" else None,
        research_tool_handler=(
            research_tool_handler_for_chat(
                session,
                persona=persona,
                history=history,
                user_message=body.message,
            )
            if persona.kind == "expert"
            else None
        ),
    )

    user_row = PersonaMessage(
        persona_id=persona_id,
        mode=body.mode,
        role="user",
        content=body.message,
        image_sha256=body.image_sha256,
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
    saved_memories = await remember_expert_chat_turn(
        persona,
        message=body.message,
        reply=reply,
        image_sha256=body.image_sha256,
    )

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
    return PersonaChatResponse(
        reply=reply,
        messages=messages,
        suggestions=suggestions,
        saved_memories=saved_memories,
    )


@router.delete("/{persona_id}/messages", status_code=204)
async def clear_messages(
    persona_id: str,
    mode: ChatMode = Query(default="interview"),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
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
    user: UserAccount = Depends(get_current_user),
) -> PersonaMessageDeleteResponse:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
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
    user: UserAccount = Depends(get_current_user),
) -> PersonaChatResponse:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
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
    prompts = await require_prompts_for_persona(session, persona)
    mode = target.mode

    if target.role == "user":
        history = [(row.role, row.content, row.image_sha256) for row in kept]
        user_message = target.content
        image_sha256 = target.image_sha256
        memory_context = await expert_memory_context(
            persona, user_message, prompts, image_sha256=image_sha256
        )
        evidence_context = ""
        if persona.kind == "expert":
            evidence_context = await reusable_expert_chat_evidence_context(
                session,
                customer_id=persona.customer_id,
                question=user_message,
                prompts=prompts,
            )
        reply = await reply_as_persona(
            profile,
            mode,
            history,
            user_message,
            prompts=prompts,
            area_block=area_block,
            extra_system=combine_expert_chat_context(memory_context, evidence_context),
            user_image_sha256=image_sha256,
            profile_kind=persona.kind,
            tools=persona.tools,
            research_tool_handler=(
                research_tool_handler_for_chat(
                    session,
                    persona=persona,
                    history=history,
                    user_message=user_message,
                )
                if persona.kind == "expert"
                else None
            ),
        )
        session.add(
            PersonaMessage(
                persona_id=persona_id,
                mode=mode,
                role="user",
                content=user_message,
                image_sha256=image_sha256,
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
        image_sha256 = kept[-1].image_sha256
        history = [(row.role, row.content, row.image_sha256) for row in kept[:-1]]
        memory_context = await expert_memory_context(
            persona, user_message, prompts, image_sha256=image_sha256
        )
        evidence_context = ""
        if persona.kind == "expert":
            evidence_context = await reusable_expert_chat_evidence_context(
                session,
                customer_id=persona.customer_id,
                question=user_message,
                prompts=prompts,
            )
        reply = await reply_as_persona(
            profile,
            mode,
            history,
            user_message,
            prompts=prompts,
            area_block=area_block,
            extra_system=combine_expert_chat_context(memory_context, evidence_context),
            user_image_sha256=image_sha256,
            profile_kind=persona.kind,
            tools=persona.tools,
            research_tool_handler=(
                research_tool_handler_for_chat(
                    session,
                    persona=persona,
                    history=history,
                    user_message=user_message,
                )
                if persona.kind == "expert"
                else None
            ),
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
    saved_memories = await remember_expert_chat_turn(
        persona,
        message=user_message,
        reply=reply,
        image_sha256=image_sha256,
    )

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
    return PersonaChatResponse(
        reply=reply,
        messages=messages,
        suggestions=suggestions,
        saved_memories=saved_memories,
    )


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    persona = await _get_persona(session, persona_id)
    assert_kund_access(user, persona.customer_id)
    old_key = persona.avatar_key
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
    if old_key:
        await delete_object(PERSONA_AVATAR_BUCKET, old_key)
