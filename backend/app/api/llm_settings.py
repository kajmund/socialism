"""Admin endpoints for chat LLM configurations and probe metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.config import settings
from app.database.session import get_session
from app.llm import stream_text_with_metrics
from app.services import llm_runtime_settings as runtime

router = APIRouter(
    prefix="/llm",
    tags=["llm"],
    dependencies=[Depends(require_admin)],
)

# Non-admin: chat UI needs to know if the attach button should show.
capabilities_router = APIRouter(prefix="/llm", tags=["llm"])


class LlmActiveOut(BaseModel):
    profile_id: str
    provider: str
    model: str
    temperature: float | None
    top_p: float | None
    max_tokens: int
    reasoning_effort: str | None


class LlmConfigurationOut(BaseModel):
    id: int
    name: str
    profile_id: str
    provider: str
    model: str
    temperature: float | None
    top_p: float | None
    max_tokens: int
    reasoning_effort: str | None
    is_default: bool
    created_at: str
    updated_at: str


class LlmGetOut(BaseModel):
    catalog: list[dict]
    active: LlmActiveOut
    credentials: dict[str, bool]
    configurations: list[LlmConfigurationOut]
    default_id: int | None
    assignments: dict[str, int]


class LlmPutIn(BaseModel):
    profile_id: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None


class LlmConfigurationCreateIn(BaseModel):
    name: str
    profile_id: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    is_default: bool = False


class LlmConfigurationUpdateIn(BaseModel):
    name: str | None = None
    profile_id: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None


class LlmPromptAssignmentIn(BaseModel):
    llm_configuration_id: int | None = None


class LlmProbeIn(BaseModel):
    prompt: str = Field(min_length=1)
    system: str | None = None
    # Optional one-shot overrides (do not persist).
    profile_id: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None


class LlmProbeOut(BaseModel):
    response: str
    provider: str
    model: str
    reasoning_effort: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    round_trip_ms: float
    time_to_first_token_ms: float | None
    completion_tokens_per_second: float | None
    finish_reason: str | None


def _active_out() -> LlmActiveOut:
    return LlmActiveOut(**runtime.active_settings_dict())


def _configuration_out(row: object) -> LlmConfigurationOut:
    return LlmConfigurationOut(**runtime.configuration_as_dict(row))  # type: ignore[arg-type]


async def _get_payload(session: AsyncSession) -> LlmGetOut:
    rows = await runtime.list_configurations(session)
    default = next((row for row in rows if row.is_default), None)
    return LlmGetOut(
        catalog=runtime.catalog_as_dicts(),
        active=_active_out(),
        credentials=runtime.credentials_status(),
        configurations=[_configuration_out(row) for row in rows],
        default_id=default.id if default is not None else None,
        assignments=await runtime.assignment_map(session),
    )


@router.get("", response_model=LlmGetOut)
async def get_llm_settings(
    session: AsyncSession = Depends(get_session),
) -> LlmGetOut:
    return await _get_payload(session)


@router.put("", response_model=LlmActiveOut)
async def put_llm_settings(
    body: LlmPutIn,
    session: AsyncSession = Depends(get_session),
) -> LlmActiveOut:
    try:
        await runtime.save_runtime_settings(
            session,
            profile_id=body.profile_id,
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_tokens if body.max_tokens is not None else settings.llm_max_tokens,
            reasoning_effort=body.reasoning_effort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _active_out()


@router.get("/configurations", response_model=list[LlmConfigurationOut])
async def list_llm_configurations(
    session: AsyncSession = Depends(get_session),
) -> list[LlmConfigurationOut]:
    rows = await runtime.list_configurations(session)
    return [_configuration_out(row) for row in rows]


@router.post("/configurations", response_model=LlmConfigurationOut, status_code=201)
async def create_llm_configuration(
    body: LlmConfigurationCreateIn,
    session: AsyncSession = Depends(get_session),
) -> LlmConfigurationOut:
    try:
        row = await runtime.create_configuration(
            session,
            name=body.name,
            profile_id=body.profile_id,
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_tokens,
            reasoning_effort=body.reasoning_effort,
            is_default=body.is_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _configuration_out(row)


@router.patch("/configurations/{configuration_id}", response_model=LlmConfigurationOut)
async def update_llm_configuration(
    configuration_id: int,
    body: LlmConfigurationUpdateIn,
    session: AsyncSession = Depends(get_session),
) -> LlmConfigurationOut:
    try:
        row = await runtime.update_configuration(
            session,
            configuration_id,
            name=body.name,
            profile_id=body.profile_id,
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_tokens,
            reasoning_effort=body.reasoning_effort,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _configuration_out(row)


@router.post(
    "/configurations/{configuration_id}/default",
    response_model=LlmConfigurationOut,
)
async def set_default_llm_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> LlmConfigurationOut:
    try:
        row = await runtime.set_default_configuration(session, configuration_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _configuration_out(row)


@router.delete("/configurations/{configuration_id}", status_code=204)
async def delete_llm_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await runtime.delete_configuration(session, configuration_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/prompt-fields/{prompt_key:path}", response_model=LlmGetOut)
async def assign_prompt_llm_configuration(
    prompt_key: str,
    body: LlmPromptAssignmentIn,
    session: AsyncSession = Depends(get_session),
) -> LlmGetOut:
    try:
        await runtime.assign_prompt_configuration(
            session, prompt_key, body.llm_configuration_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _get_payload(session)


@router.post("/probe", response_model=LlmProbeOut)
async def post_llm_probe(body: LlmProbeIn) -> LlmProbeOut:
    snapshot = {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_temperature": settings.llm_temperature,
        "llm_top_p": settings.llm_top_p,
        "llm_max_tokens": settings.llm_max_tokens,
        "llm_reasoning_effort": settings.llm_reasoning_effort,
        "deepseek_model": settings.deepseek_model,
    }
    overridden = body.profile_id is not None
    probe_revision: int | None = None
    metrics = None
    probe_provider = settings.llm_provider
    probe_model = settings.selected_llm_model
    probe_effort = settings.selected_reasoning_effort
    try:
        if overridden:
            normalized = runtime.validate_and_normalize(
                profile_id=body.profile_id,
                temperature=body.temperature,
                top_p=body.top_p,
                max_tokens=body.max_tokens,
                reasoning_effort=body.reasoning_effort,
            )
            runtime.apply_runtime_settings(
                profile_id=normalized["profile_id"],
                temperature=normalized["temperature"],
                top_p=normalized["top_p"],
                max_tokens=int(normalized["max_tokens"]),
                reasoning_effort=normalized["reasoning_effort"],
            )
            probe_revision = runtime.settings_revision()
        messages: list[dict[str, str]] = []
        if body.system and body.system.strip():
            messages.append({"role": "system", "content": body.system.strip()})
        messages.append({"role": "user", "content": body.prompt.strip()})
        probe_provider = settings.llm_provider
        probe_model = settings.selected_llm_model
        probe_effort = settings.selected_reasoning_effort
        metrics = await stream_text_with_metrics(messages)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if (
            overridden
            and probe_revision is not None
            and runtime.settings_revision() == probe_revision
        ):
            runtime.restore_runtime_settings_snapshot(snapshot)

    assert metrics is not None
    elapsed_s = metrics.elapsed_ms / 1000.0 if metrics.elapsed_ms > 0 else 0.0
    tps = (
        metrics.completion_tokens / elapsed_s
        if elapsed_s > 0 and metrics.completion_tokens > 0
        else None
    )
    return LlmProbeOut(
        response=metrics.text,
        provider=probe_provider,
        model=probe_model,
        reasoning_effort=probe_effort,
        prompt_tokens=metrics.prompt_tokens,
        completion_tokens=metrics.completion_tokens,
        total_tokens=metrics.prompt_tokens + metrics.completion_tokens,
        round_trip_ms=metrics.elapsed_ms,
        time_to_first_token_ms=metrics.time_to_first_token_ms,
        completion_tokens_per_second=tps,
        finish_reason=metrics.finish_reason,
    )


class LlmCapabilitiesOut(BaseModel):
    supports_vision: bool
    provider: str
    model: str
    profile_id: str
    allowed_image_types: list[str]


@capabilities_router.get("/capabilities", response_model=LlmCapabilitiesOut)
async def get_llm_capabilities(
    _user: object = Depends(get_current_user),
) -> LlmCapabilitiesOut:
    return LlmCapabilitiesOut(**runtime.active_vision_capabilities())
