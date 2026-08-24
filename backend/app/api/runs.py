from copy import deepcopy
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Message, Persona, PersonaMessage, Population, Run
from app.database.session import get_session
from app.llm.chat import build_run_interview_prompt, reply_as_persona
from app.services.prompt_store import require_active_prompts
from app.schemas.domain import (
    JobCreate,
    OasisRunOptions,
    PersonaChatResponse,
    PersonaMessageOut,
    RunAnchorPoolAddRequest,
    RunCreate,
    RunDetail,
    RunLogTailOut,
    RunMisclassificationFlagCreate,
    RunPersonaInterviewRequest,
    RunPopulationOption,
    RunSummary,
    RunTaggableTextsOut,
    RunUpdate,
    SsrMisclassificationFlagOut,
    format_date,
)
from app.serializers import (
    parse_optional_date,
    profile_from_dict,
    serialize_run_detail,
    serialize_run_summary,
    utcnow,
)
from app.services import jobs as jobs_service
from app.services.anchor_pool import (
    AnchorPoolError,
    active_anchor_context,
    add_pool_item,
    list_tagger_texts,
    resolve_active_anchor_set_ids,
)
from app.services.anchor_store import AnchorResolutionError
from app.services.district_context import area_block_for_name
from app.services.misclassification_flags import (
    MisclassificationFlagError,
    create_flag,
    serialize_flag,
)
from app.services.oasis_run import oasis_installed, previous_attempts, remove_attempt
from app.services.run_log import read_run_log_tail
from app.services.run_results import find_attempt, find_variant
from app.services.run_tick_context import build_persona_feed_context
from app.services.run_watch_demo import publish_run_watch_demo

router = APIRouter(prefix="/runs", tags=["runs"])


async def _get_run(session: AsyncSession, run_id: int) -> Run:
    result = await session.execute(
        select(Run).options(selectinload(Run.population)).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _ticks_payload(ticks: list) -> list:
    return [t.model_dump() if hasattr(t, "model_dump") else t for t in ticks]


def _branch_payload(branch) -> dict | None:
    if branch is None:
        return None
    return branch.model_dump() if hasattr(branch, "model_dump") else branch


def _oasis_options_payload(options) -> dict:
    if options is None:
        return OasisRunOptions().model_dump()
    if isinstance(options, OasisRunOptions):
        return options.model_dump()
    return OasisRunOptions.model_validate(options).model_dump()


from app.api.message_images import resolve_message_feed_body


async def _snapshot_message_bodies(session: AsyncSession, run: Run) -> None:
    """Freeze library Message body + image caption into Injection.text before start."""

    def collect_ids(ticks: list[Any]) -> set[str]:
        ids: set[str] = set()
        for tick in ticks or []:
            for inj in (tick.get("injections") if isinstance(tick, dict) else []) or []:
                mid = inj.get("message_id") if isinstance(inj, dict) else None
                if mid:
                    ids.add(mid)
        return ids

    message_ids = collect_ids(run.main_ticks or [])
    branch = run.branch or {}
    if isinstance(branch, dict):
        message_ids |= collect_ids(branch.get("a") or [])
        message_ids |= collect_ids(branch.get("b") or [])

    if not message_ids:
        return

    result = await session.execute(select(Message).where(Message.id.in_(message_ids)))
    by_id = {m.id: m for m in result.scalars().all()}
    missing = sorted(message_ids - set(by_id))
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Referenced messages not found: {', '.join(missing)}",
        )

    def apply(ticks: list[Any]) -> list[Any]:
        out = deepcopy(ticks or [])
        for tick in out:
            if not isinstance(tick, dict):
                continue
            for inj in tick.get("injections") or []:
                if not isinstance(inj, dict):
                    continue
                mid = inj.get("message_id")
                if mid and mid in by_id:
                    msg = by_id[mid]
                    try:
                        inj["text"] = resolve_message_feed_body(
                            body=str(msg.body or ""),
                            metadata=dict(msg.metadata_ or {}),
                        )
                    except ValueError as exc:
                        raise HTTPException(status_code=400, detail=str(exc)) from exc
        return out

    run.main_ticks = apply(run.main_ticks or [])
    if isinstance(branch, dict) and branch:
        run.branch = {
            **branch,
            "a": apply(branch.get("a") or []),
            "b": apply(branch.get("b") or []),
        }


@router.get("", response_model=list[RunSummary])
async def list_runs(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[RunSummary]:
    stmt = select(Run).options(selectinload(Run.population)).order_by(Run.updated_at.desc())
    if status:
        stmt = stmt.where(Run.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Run.name.ilike(like))
    result = await session.execute(stmt)
    runs = list(result.scalars().all())
    return [serialize_run_summary(run, run.population.name) for run in runs]


@router.get("/populations", response_model=list[RunPopulationOption])
async def list_run_populations(
    session: AsyncSession = Depends(get_session),
) -> list[RunPopulationOption]:
    result = await session.execute(
        select(Population)
        .options(selectinload(Population.members))
        .order_by(Population.name)
    )
    populations = list(result.scalars().all())
    out: list[RunPopulationOption] = []
    for population in populations:
        initials = [m.initials for m in population.members[:3]]
        out.append(
            RunPopulationOption(
                id=population.id,
                name=population.name,
                size=population.size,
                initials=initials,
            )
        )
    return out


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    run = await _get_run(session, run_id)
    return serialize_run_detail(run, run.population.name)


@router.post("", response_model=RunDetail, status_code=201)
async def create_run(
    body: RunCreate,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    population = await session.get(Population, body.population_id)
    if population is None:
        raise HTTPException(status_code=404, detail="Population not found")
    run = Run(
        name=body.name,
        status=body.status,
        population_id=body.population_id,
        seed="",
        start_date=parse_optional_date(body.start_date),
        main_ticks=_ticks_payload(body.main_ticks),
        branch=_branch_payload(body.branch),
        oasis_options=_oasis_options_payload(body.oasis_options),
        updated_at=utcnow(),
    )
    session.add(run)
    await session.commit()
    run = await _get_run(session, run.id)
    return serialize_run_detail(run, run.population.name)


@router.put("/{run_id}", response_model=RunDetail)
async def update_run(
    run_id: int,
    body: RunUpdate,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    run = await _get_run(session, run_id)
    data = body.model_dump(exclude_unset=True)
    if "population_id" in data:
        population = await session.get(Population, data["population_id"])
        if population is None:
            raise HTTPException(status_code=404, detail="Population not found")
    if "start_date" in data:
        data["start_date"] = parse_optional_date(data["start_date"])
    if "main_ticks" in data and data["main_ticks"] is not None:
        data["main_ticks"] = _ticks_payload(data["main_ticks"])
    if "branch" in data and data["branch"] is not None:
        data["branch"] = _branch_payload(data["branch"])
    if "oasis_options" in data and data["oasis_options"] is not None:
        data["oasis_options"] = _oasis_options_payload(data["oasis_options"])
    for key, value in data.items():
        setattr(run, key, value)
    run.updated_at = utcnow()
    await session.commit()
    run = await _get_run(session, run_id)
    return serialize_run_detail(run, run.population.name)


@router.post("/{run_id}/start", response_model=RunDetail, status_code=202)
async def start_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    """Queue simulation as a background job; returns immediately with status=running."""
    run = await _get_run(session, run_id)
    if run.status == "running":
        raise HTTPException(status_code=409, detail="Run is already running")

    if settings.simulation_engine == "oasis":
        if not settings.deepseek_api_key:
            raise HTTPException(
                status_code=503,
                detail="DEEPSEEK_API_KEY is required when SIMULATION_ENGINE=oasis",
            )
        if not oasis_installed():
            raise HTTPException(
                status_code=503,
                detail="camel-oasis is not installed. Run: uv sync --extra oasis",
            )

    await _snapshot_message_bodies(session, run)

    # Atomic flip so concurrent /start cannot queue two workers for the same run.
    prior_status = run.status
    now = utcnow()
    flipped = await session.execute(
        update(Run)
        .where(Run.id == run_id, Run.status == prior_status)
        .values(
            status="running",
            updated_at=now,
            main_ticks=run.main_ticks,
            branch=run.branch,
        )
    )
    if int(flipped.rowcount or 0) != 1:
        raise HTTPException(status_code=409, detail="Run is already running")
    await session.commit()

    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind="run_simulate",
            label=run.name,
            request={"run_id": run.id},
        ),
    )

    run = await _get_run(session, run_id)
    detail = serialize_run_detail(run, run.population.name).model_copy(
        update={"job_id": job.id}
    )
    # Enqueue after the response payload is ready so the worker cannot
    # starve the event loop before we return 202.
    jobs_service.enqueue_job(job.id)
    return detail


@router.post("/{run_id}/duplicate", response_model=RunDetail, status_code=201)
async def duplicate_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    source = await _get_run(session, run_id)
    run = Run(
        name=f"{source.name} (kopia)",
        status="draft",
        population_id=source.population_id,
        seed="",
        start_date=source.start_date,
        main_ticks=list(source.main_ticks or []),
        branch=dict(source.branch) if source.branch else None,
        oasis_options=dict(source.oasis_options or {}),
        updated_at=utcnow(),
    )
    session.add(run)
    await session.commit()
    run = await _get_run(session, run.id)
    return serialize_run_detail(run, run.population.name)


@router.delete("/{run_id}/results/attempts/{attempt_id}", response_model=RunDetail)
async def delete_run_result_attempt(
    run_id: int,
    attempt_id: str,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    """Remove one saved simulation attempt from the run's results history."""
    run = await _get_run(session, run_id)
    if run.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete results while the run is simulating",
        )
    try:
        run.results = remove_attempt(
            run.results if isinstance(run.results, dict) else None,
            attempt_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Result attempt not found") from exc
    run.updated_at = utcnow()
    await session.commit()
    run = await _get_run(session, run_id)
    return serialize_run_detail(run, run.population.name)


def _serialize_persona_message(row: PersonaMessage) -> PersonaMessageOut:
    asked_by = row.asked_by if row.asked_by in {"doctor", "human"} else None
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
        asked_by=asked_by,  # type: ignore[arg-type]
    )


def _find_attempt_variant(
    results: dict[str, Any] | None,
    attempt_id: str,
    variant_id: str,
) -> dict[str, Any]:
    attempts = previous_attempts(results)
    attempt = next((a for a in attempts if a.get("id") == attempt_id), None)
    if attempt is None and attempt_id == "legacy" and results:
        # Legacy flat shape treated as a single attempt.
        variants = results.get("variants") or []
        for variant in variants:
            if variant.get("id") == variant_id:
                return variant
        if results.get("posts") is not None or results.get("agents") is not None:
            if variant_id == "main":
                return {
                    "id": "main",
                    "agents": results.get("agents") or [],
                    "posts": results.get("posts") or [],
                    "comments": results.get("comments") or [],
                    "trace": results.get("trace") or [],
                    "tick_markers": results.get("tick_markers") or [],
                    "ticks_run": results.get("ticks_run"),
                }
    if attempt is None:
        raise HTTPException(status_code=404, detail="Result attempt not found")
    for variant in attempt.get("variants") or []:
        if variant.get("id") == variant_id:
            return variant
    raise HTTPException(status_code=404, detail="Result variant not found")


def _run_interview_filter(
    *,
    persona_id: str,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    through_tick_index: int,
):
    return (
        PersonaMessage.persona_id == persona_id,
        PersonaMessage.mode == "interview",
        PersonaMessage.run_id == run_id,
        PersonaMessage.attempt_id == attempt_id,
        PersonaMessage.variant_id == variant_id,
        PersonaMessage.through_tick_index == through_tick_index,
    )


def _validate_interview_variant(
    run: Run,
    variant: dict[str, Any],
    *,
    persona_id: str,
    through_tick_index: int,
) -> None:
    if run.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Cannot interview while the run is simulating",
        )
    markers = variant.get("tick_markers") or []
    ticks_run = int(variant.get("ticks_run") or 0)
    if through_tick_index < 0 or through_tick_index >= len(markers):
        raise HTTPException(status_code=400, detail="through_tick_index out of range")
    if ticks_run > 0 and through_tick_index > ticks_run - 1:
        raise HTTPException(status_code=400, detail="through_tick_index beyond ticks_run")
    agents = variant.get("agents") or []
    if not any(
        a.get("persona_id") == persona_id and a.get("role") != "injector"
        for a in agents
    ):
        raise HTTPException(
            status_code=404,
            detail="Persona not found in this simulation variant",
        )


@router.get(
    "/{run_id}/attempts/{attempt_id}/variants/{variant_id}/personas/{persona_id}/interview",
    response_model=list[PersonaMessageOut],
)
async def list_run_persona_interview(
    run_id: int,
    attempt_id: str,
    variant_id: str,
    persona_id: str,
    through_tick_index: int = Query(ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[PersonaMessageOut]:
    run = await _get_run(session, run_id)
    variant = _find_attempt_variant(
        run.results if isinstance(run.results, dict) else None,
        attempt_id,
        variant_id,
    )
    _validate_interview_variant(
        run, variant, persona_id=persona_id, through_tick_index=through_tick_index
    )
    result = await session.execute(
        select(PersonaMessage)
        .where(
            *_run_interview_filter(
                persona_id=persona_id,
                run_id=run_id,
                attempt_id=attempt_id,
                variant_id=variant_id,
                through_tick_index=through_tick_index,
            )
        )
        .order_by(PersonaMessage.id.asc())
    )
    return [_serialize_persona_message(row) for row in result.scalars().all()]


@router.post(
    "/{run_id}/attempts/{attempt_id}/variants/{variant_id}/personas/{persona_id}/interview",
    response_model=PersonaChatResponse,
)
async def run_persona_interview(
    run_id: int,
    attempt_id: str,
    variant_id: str,
    persona_id: str,
    body: RunPersonaInterviewRequest,
    session: AsyncSession = Depends(get_session),
) -> PersonaChatResponse:
    run = await _get_run(session, run_id)
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona not found")

    variant = _find_attempt_variant(
        run.results if isinstance(run.results, dict) else None,
        attempt_id,
        variant_id,
    )
    _validate_interview_variant(
        run,
        variant,
        persona_id=persona_id,
        through_tick_index=body.through_tick_index,
    )

    try:
        feed_context, meta = build_persona_feed_context(
            variant,
            persona_id=persona_id,
            through_tick_index=body.through_tick_index,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    profile = profile_from_dict(persona.profile, persona.name)
    area_block = await area_block_for_name(session, profile.ort or persona.district)
    prompts = await require_active_prompts(session)
    system_prompt = build_run_interview_prompt(
        profile,
        feed_context,
        prompts=prompts,
        day=int(meta["day"]),
        tick_index=int(meta["tick_index"]),
        area_block=area_block,
    )

    history_rows = await session.execute(
        select(PersonaMessage)
        .where(
            *_run_interview_filter(
                persona_id=persona_id,
                run_id=run_id,
                attempt_id=attempt_id,
                variant_id=variant_id,
                through_tick_index=body.through_tick_index,
            )
        )
        .order_by(PersonaMessage.id.asc())
    )
    history = [(row.role, row.content) for row in history_rows.scalars().all()]

    reply = await reply_as_persona(
        profile,
        "interview",
        history,
        body.message,
        prompts=prompts,
        system_prompt=system_prompt,
    )

    user_row = PersonaMessage(
        persona_id=persona_id,
        mode="interview",
        role="user",
        content=body.message,
        created_at=utcnow(),
        run_id=run_id,
        attempt_id=attempt_id,
        variant_id=variant_id,
        through_tick_index=body.through_tick_index,
        asked_by="human",
    )
    assistant_row = PersonaMessage(
        persona_id=persona_id,
        mode="interview",
        role="assistant",
        content=reply,
        created_at=utcnow(),
        run_id=run_id,
        attempt_id=attempt_id,
        variant_id=variant_id,
        through_tick_index=body.through_tick_index,
    )
    session.add(user_row)
    session.add(assistant_row)
    await session.commit()

    all_rows = await session.execute(
        select(PersonaMessage)
        .where(
            *_run_interview_filter(
                persona_id=persona_id,
                run_id=run_id,
                attempt_id=attempt_id,
                variant_id=variant_id,
                through_tick_index=body.through_tick_index,
            )
        )
        .order_by(PersonaMessage.id.asc())
    )
    messages = [_serialize_persona_message(row) for row in all_rows.scalars().all()]
    return PersonaChatResponse(reply=reply, messages=messages)


@router.delete(
    "/{run_id}/attempts/{attempt_id}/variants/{variant_id}/personas/{persona_id}/interview",
    status_code=204,
)
async def clear_run_persona_interview(
    run_id: int,
    attempt_id: str,
    variant_id: str,
    persona_id: str,
    through_tick_index: int = Query(ge=0),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _get_run(session, run_id)
    result = await session.execute(
        select(PersonaMessage).where(
            *_run_interview_filter(
                persona_id=persona_id,
                run_id=run_id,
                attempt_id=attempt_id,
                variant_id=variant_id,
                through_tick_index=through_tick_index,
            )
        )
    )
    for row in result.scalars().all():
        await session.delete(row)
    await session.commit()


@router.get("/{run_id}/taggable-texts", response_model=RunTaggableTextsOut)
async def get_run_taggable_texts(
    run_id: int,
    attempt_id: str = Query(min_length=1),
    variant_id: str = Query(min_length=1),
    locale: str = Query(default="sv", pattern="^(sv|en)$"),
    include_ssr: bool = Query(
        default=True,
        description=(
            "When true (default), classify each text with SSR against the active "
            "configuration's tone/style anchors. Requires anchors; returns 409 if missing."
        ),
    ),
    session: AsyncSession = Depends(get_session),
) -> RunTaggableTextsOut:
    """Comments and interview answers from a finished attempt for SSR pool tagging.

    With ``include_ssr=true``, each row includes ``tone_predicted`` / ``style_predicted``
    (argmax) and optional PMFs from the same embedding path used by reports.
    """
    await _get_run(session, run_id)
    try:
        payload = await list_tagger_texts(
            session,
            run_id=run_id,
            attempt_id=attempt_id,
            variant_id=variant_id,
            locale=locale,  # type: ignore[arg-type]
            include_ssr=include_ssr,
        )
    except AnchorPoolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnchorResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RunTaggableTextsOut.model_validate(payload)


@router.post(
    "/{run_id}/misclassification-flags",
    response_model=SsrMisclassificationFlagOut,
    status_code=201,
)
async def create_run_misclassification_flag(
    run_id: int,
    body: RunMisclassificationFlagCreate,
    session: AsyncSession = Depends(get_session),
) -> SsrMisclassificationFlagOut:
    """Flag an SSR misprediction on a run text against the active config's anchor set."""
    await _get_run(session, run_id)
    try:
        flag = await create_flag(
            session,
            kind=body.kind,
            text=body.text,
            predicted_label=body.predicted_label,
            expected_label=body.expected_label,
            source_type=body.source_type,
            source_ref=body.source_ref,
            source_run_id=run_id,
            source_attempt_id=body.attempt_id,
            source_variant_id=body.variant_id,
            locale=body.locale,
        )
    except AnchorResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MisclassificationFlagError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(flag)
    return SsrMisclassificationFlagOut.model_validate(serialize_flag(flag))


@router.post("/{run_id}/anchor-pool", status_code=201)
async def add_run_anchor_pool_items(
    run_id: int,
    body: RunAnchorPoolAddRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Tag a simulation text as tone/style pool anchor(s) on the active configuration's sets."""
    await _get_run(session, run_id)
    try:
        refs = await resolve_active_anchor_set_ids(session, body.locale)
    except AnchorResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    created: list[dict] = []
    try:
        if body.tone_label:
            item = await add_pool_item(
                session,
                anchor_set_id=refs["tone"],
                label=body.tone_label,
                text=body.text,
                source_type=body.source_type,
                source_run_id=run_id,
                source_attempt_id=body.attempt_id,
                source_variant_id=body.variant_id,
                source_ref=body.source_ref,
                add_to_calibration=body.add_to_calibration,
            )
            created.append({"kind": "tone", "id": item.id, "label": item.label})
        if body.style_label:
            item = await add_pool_item(
                session,
                anchor_set_id=refs["style"],
                label=body.style_label,
                text=body.text,
                source_type=body.source_type,
                source_run_id=run_id,
                source_attempt_id=body.attempt_id,
                source_variant_id=body.variant_id,
                source_ref=body.source_ref,
                add_to_calibration=body.add_to_calibration,
            )
            created.append({"kind": "style", "id": item.id, "label": item.label})
    except AnchorPoolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    ctx = await active_anchor_context(session, body.locale)  # type: ignore[arg-type]
    return {"created": created, "anchor_context": ctx}


@router.get("/{run_id}/logs", response_model=RunLogTailOut)
async def get_run_log_tail(
    run_id: int,
    attempt: str = Query(min_length=1, max_length=64),
    variant: str = Query(min_length=1, max_length=64),
    tail: int = Query(default=200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> RunLogTailOut:
    run = await _get_run(session, run_id)
    attempt_row = find_attempt(run.results, attempt)
    if attempt_row is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if find_variant(attempt_row, variant) is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    try:
        path, content, truncated = read_run_log_tail(
            run_id=run_id,
            attempt_id=attempt,
            variant_id=variant,
            lines=tail,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Log file not found") from exc
    return RunLogTailOut(
        run_id=run_id,
        attempt_id=attempt,
        variant_id=variant,
        log_path=str(path),
        tail_lines=tail,
        truncated=truncated,
        content=content,
    )


@router.post("/{run_id}/demo-live-feed", status_code=202)
async def demo_live_feed(
    run_id: int,
    background_tasks: BackgroundTasks,
    variant_id: str = Query(default="a", min_length=1),
    delay_seconds: float = Query(default=2.0, ge=0.0, le=15.0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Dev helper: stream staged run-watch events through the running server."""
    if settings.persona_generator != "stub":
        raise HTTPException(status_code=403, detail="Demo live feed is dev-only")
    await _get_run(session, run_id)

    async def _run() -> None:
        from app.database.session import SessionLocal

        async with SessionLocal() as bg_session:
            await publish_run_watch_demo(
                bg_session,
                run_id=run_id,
                variant_id=variant_id,
                delay_seconds=delay_seconds,
            )

    background_tasks.add_task(_run)
    return {"status": "started", "variant_id": variant_id}


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    run = await _get_run(session, run_id)
    await session.delete(run)
    await session.commit()
