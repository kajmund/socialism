"""Catalog + DB-backed override for the active chat LLM (admin Tools page)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLMProvider, settings
from app.database.models import LlmConfiguration, LlmRuntimeSettings, PromptField
from app.llm import reset_client
from app.llm.runtime_override import (
    CachedLlmConfiguration,
    LlmRuntimeView,
    PromptLlmAssignmentView,
    SelectionMode,
    SelectionRole,
    set_runtime_selection_cache,
)
from app.serializers import utcnow

ProfileId = Literal[
    "deepseek-flash",
    "deepseek-v4-pro",
    "gpt-oss-120b",
    "qwen-3.8-27b",
]

SINGLETON_ID = 1
DEFAULT_CONFIGURATION_NAME = "Standard"

_settings_revision = 0

# Retired Chat Completions model id → current catalog profile.
_LEGACY_PROFILE_IDS: dict[str, ProfileId] = {
    "deepseek-chat": "deepseek-flash",
}


@dataclass(frozen=True)
class ParamSpec:
    key: str
    kind: Literal["float", "int", "enum"]
    minimum: float | None = None
    maximum: float | None = None
    default: float | int | str | None = None
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ModelProfile:
    id: ProfileId
    label: str
    provider: LLMProvider
    model: str
    params: tuple[ParamSpec, ...]
    supports_vision: bool = False
    allowed_image_types: tuple[str, ...] = ()


_TEMP = ParamSpec("temperature", "float", minimum=0, maximum=2, default=1.0)
_TOP_P = ParamSpec("top_p", "float", minimum=0.01, maximum=1, default=1.0)
# DeepSeek Chat Completions / Responses: max output 384K = 393216 tokens.
_MAX_TOKENS_DEEPSEEK = ParamSpec(
    "max_tokens", "int", minimum=1, maximum=393_216, default=8192
)
# Cerebras paid tier: gpt-oss-120b / qwen-3.8-27b max output 40k tokens.
_MAX_TOKENS_CEREBRAS = ParamSpec(
    "max_tokens", "int", minimum=1, maximum=40_000, default=8192
)
# DeepSeek: none disables thinking; low/high/max enable it (API default high).
_REASONING_DEEPSEEK = ParamSpec(
    "reasoning_effort",
    "enum",
    default="high",
    choices=("none", "low", "high", "max"),
)

_DEEPSEEK_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")
_QWEN_IMAGE_TYPES = ("image/jpeg", "image/png")

MODEL_CATALOG: tuple[ModelProfile, ...] = (
    ModelProfile(
        id="deepseek-flash",
        label="DeepSeek Flash",
        provider="deepseek",
        model="deepseek-flash",
        params=(_TEMP, _TOP_P, _MAX_TOKENS_DEEPSEEK, _REASONING_DEEPSEEK),
        supports_vision=True,
        allowed_image_types=_DEEPSEEK_IMAGE_TYPES,
    ),
    ModelProfile(
        id="deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        provider="deepseek",
        model="deepseek-v4-pro",
        params=(_TEMP, _TOP_P, _MAX_TOKENS_DEEPSEEK, _REASONING_DEEPSEEK),
        # DeepSeek accepts image parts but returns text-only replies (no pixels).
        # Native vision is on deepseek-flash (V4.1-Flash) only.
        supports_vision=False,
        allowed_image_types=(),
    ),
    ModelProfile(
        id="gpt-oss-120b",
        label="OpenAI GPT OSS",
        provider="cerebras",
        model="gpt-oss-120b",
        params=(
            _TEMP,
            _TOP_P,
            _MAX_TOKENS_CEREBRAS,
            ParamSpec(
                "reasoning_effort",
                "enum",
                default="medium",
                choices=("low", "medium", "high"),
            ),
        ),
        supports_vision=False,
        allowed_image_types=(),
    ),
    ModelProfile(
        id="qwen-3.8-27b",
        label="Qwen 3.8 27B",
        provider="cerebras",
        model="qwen-3.8-27b",
        params=(
            _TEMP,
            _TOP_P,
            _MAX_TOKENS_CEREBRAS,
            ParamSpec(
                "reasoning_effort",
                "enum",
                default="high",
                choices=("low", "medium", "high"),
            ),
        ),
        supports_vision=True,
        allowed_image_types=_QWEN_IMAGE_TYPES,
    ),
)

_CATALOG_BY_ID = {row.id: row for row in MODEL_CATALOG}

SELECTION_ROLES: tuple[SelectionRole, ...] = ("fast", "balanced", "deep")
SELECTION_MODES: tuple[SelectionMode, ...] = ("default", "fixed", "auto")
DEFAULT_AUTO_PRIORITY = 100


def default_selection_metadata(profile_id: str) -> dict[str, Any]:
    profile = get_profile(profile_id)
    if profile.id == "deepseek-v4-pro":
        role: SelectionRole = "deep"
    elif profile.id in {"deepseek-flash", "qwen-3.8-27b"}:
        role = "fast"
    else:
        role = "balanced"
    return {
        "selection_role": role,
        "capability_vision": profile.supports_vision,
        "capability_tools": True,
        "capability_structured_output": True,
        "capability_long_context": profile.provider == "deepseek",
        "enabled_for_auto": True,
        "priority": DEFAULT_AUTO_PRIORITY,
    }


def normalize_selection_metadata(
    *,
    profile_id: str,
    selection_role: str | None = None,
    capability_vision: bool | None = None,
    capability_tools: bool | None = None,
    capability_structured_output: bool | None = None,
    capability_long_context: bool | None = None,
    enabled_for_auto: bool | None = None,
    priority: int | None = None,
) -> dict[str, Any]:
    defaults = default_selection_metadata(profile_id)
    role = defaults["selection_role"] if selection_role is None else str(selection_role)
    if role not in SELECTION_ROLES:
        raise ValueError(f"selection_role must be one of {list(SELECTION_ROLES)}")
    vision = (
        defaults["capability_vision"]
        if capability_vision is None
        else bool(capability_vision)
    )
    profile = get_profile(profile_id)
    if vision and not profile.supports_vision:
        raise ValueError(
            f"profile {profile.id} does not support vision; capability_vision cannot be true"
        )
    priority_value = defaults["priority"] if priority is None else int(priority)
    if priority_value < 0 or priority_value > 1_000_000:
        raise ValueError("priority must be between 0 and 1000000")
    return {
        "selection_role": role,
        "capability_vision": vision,
        "capability_tools": (
            defaults["capability_tools"]
            if capability_tools is None
            else bool(capability_tools)
        ),
        "capability_structured_output": (
            defaults["capability_structured_output"]
            if capability_structured_output is None
            else bool(capability_structured_output)
        ),
        "capability_long_context": (
            defaults["capability_long_context"]
            if capability_long_context is None
            else bool(capability_long_context)
        ),
        "enabled_for_auto": (
            defaults["enabled_for_auto"]
            if enabled_for_auto is None
            else bool(enabled_for_auto)
        ),
        "priority": priority_value,
    }


def resolve_profile_id(profile_id: str) -> ProfileId:
    mapped = _LEGACY_PROFILE_IDS.get(profile_id, profile_id)
    if mapped not in _CATALOG_BY_ID:
        raise ValueError(f"unknown LLM profile: {profile_id}")
    return mapped  # type: ignore[return-value]


def catalog_as_dicts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in MODEL_CATALOG:
        params = []
        for spec in profile.params:
            item: dict[str, Any] = {
                "key": spec.key,
                "kind": spec.kind,
                "default": spec.default,
            }
            if spec.minimum is not None:
                item["minimum"] = spec.minimum
            if spec.maximum is not None:
                item["maximum"] = spec.maximum
            if spec.choices is not None:
                item["choices"] = list(spec.choices)
            params.append(item)
        rows.append(
            {
                "id": profile.id,
                "label": profile.label,
                "provider": profile.provider,
                "model": profile.model,
                "supports_vision": profile.supports_vision,
                "allowed_image_types": list(profile.allowed_image_types),
                "params": params,
            }
        )
    return rows


def active_vision_capabilities() -> dict[str, Any]:
    profile = get_profile(_infer_profile_id())
    return {
        "supports_vision": profile.supports_vision,
        "provider": profile.provider,
        "model": profile.model,
        "profile_id": profile.id,
        "allowed_image_types": list(profile.allowed_image_types),
    }


def require_vision_support() -> ModelProfile:
    profile = get_profile(_infer_profile_id())
    if not profile.supports_vision:
        raise ValueError(
            f"Active model {profile.model!r} does not support image inputs "
            f"(profile {profile.id})"
        )
    return profile


def allowed_image_types_for_active() -> frozenset[str]:
    profile = get_profile(_infer_profile_id())
    return frozenset(profile.allowed_image_types)


def get_profile(profile_id: str) -> ModelProfile:
    return _CATALOG_BY_ID[resolve_profile_id(profile_id)]


def credentials_status() -> dict[str, bool]:
    return {
        "cerebras": bool(settings.cerebras_api_key.strip()),
        "deepseek": bool(settings.deepseek_api_key.strip()),
    }


def active_settings_dict() -> dict[str, Any]:
    profile_id = _infer_profile_id()
    profile = get_profile(profile_id)
    return {
        "profile_id": profile.id,
        "provider": settings.llm_provider,
        "model": settings.selected_llm_model,
        "temperature": settings.llm_temperature,
        "top_p": settings.llm_top_p,
        "max_tokens": settings.llm_max_tokens,
        "reasoning_effort": settings.selected_reasoning_effort,
    }


def _infer_profile_id() -> ProfileId:
    model = settings.selected_llm_model
    provider = settings.llm_provider
    for profile in MODEL_CATALOG:
        if profile.provider == provider and profile.model == model:
            return profile.id
    if provider == "deepseek":
        legacy = _LEGACY_PROFILE_IDS.get(model)
        if legacy is not None:
            return legacy
        return "deepseek-flash"
    if model == "qwen-3.8-27b":
        return "qwen-3.8-27b"
    return "gpt-oss-120b"


def validate_and_normalize(
    *,
    profile_id: str,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    profile = get_profile(profile_id)
    values: dict[str, Any] = {
        "profile_id": profile.id,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }
    for spec in profile.params:
        raw = values.get(spec.key)
        if raw is None:
            values[spec.key] = spec.default
            continue
        if spec.kind == "float":
            number = float(raw)
            if spec.minimum is not None and number < spec.minimum:
                raise ValueError(f"{spec.key} must be >= {spec.minimum}")
            if spec.maximum is not None and number > spec.maximum:
                raise ValueError(f"{spec.key} must be <= {spec.maximum}")
            values[spec.key] = number
        elif spec.kind == "int":
            number_i = int(raw)
            if spec.minimum is not None and number_i < spec.minimum:
                raise ValueError(f"{spec.key} must be >= {int(spec.minimum)}")
            if spec.maximum is not None and number_i > spec.maximum:
                raise ValueError(f"{spec.key} must be <= {int(spec.maximum)}")
            values[spec.key] = number_i
        elif spec.kind == "enum":
            text = str(raw)
            if spec.choices is not None and text not in spec.choices:
                raise ValueError(
                    f"{spec.key} must be one of {list(spec.choices)}, got {text!r}"
                )
            values[spec.key] = text
    if values.get("reasoning_effort") is None:
        effort_spec = next(
            (p for p in profile.params if p.key == "reasoning_effort"), None
        )
        if effort_spec is not None:
            values["reasoning_effort"] = effort_spec.default
    return values


def settings_revision() -> int:
    return _settings_revision


def restore_runtime_settings_snapshot(snapshot: dict[str, Any]) -> None:
    """Restore in-memory LLM settings without touching the database."""
    global _settings_revision
    settings.llm_provider = snapshot["llm_provider"]
    settings.llm_model = snapshot["llm_model"]
    settings.llm_temperature = snapshot["llm_temperature"]
    settings.llm_top_p = snapshot["llm_top_p"]
    settings.llm_max_tokens = snapshot["llm_max_tokens"]
    settings.llm_reasoning_effort = snapshot["llm_reasoning_effort"]
    settings.deepseek_model = snapshot["deepseek_model"]
    _settings_revision += 1
    reset_client()


def apply_runtime_settings(
    *,
    profile_id: str,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int,
    reasoning_effort: str | None,
) -> None:
    global _settings_revision
    profile = get_profile(profile_id)
    if not credentials_status().get(profile.provider):
        raise ValueError(f"API key missing for provider {profile.provider}")
    settings.llm_provider = profile.provider
    settings.llm_model = profile.model
    settings.llm_temperature = temperature
    settings.llm_top_p = top_p
    settings.llm_max_tokens = max_tokens
    if reasoning_effort is None:
        raise ValueError("reasoning_effort required for all LLM profiles")
    settings.llm_reasoning_effort = reasoning_effort  # type: ignore[assignment]
    if profile.provider == "deepseek":
        settings.deepseek_model = profile.model
    _settings_revision += 1
    reset_client()


async def load_runtime_settings(session: AsyncSession) -> bool:
    """Apply the default named configuration, or the legacy singleton."""
    default = await get_default_configuration(session)
    source: LlmConfiguration | LlmRuntimeSettings | None = default
    if source is None:
        source = await session.get(LlmRuntimeSettings, SINGLETON_ID)
    if source is None:
        await refresh_prompt_runtime_cache(session)
        return False
    if default is None and isinstance(source, LlmRuntimeSettings):
        await _upsert_default_from_values(
            session,
            profile_id=source.profile_id,
            temperature=source.temperature,
            top_p=source.top_p,
            max_tokens=source.max_tokens,
            reasoning_effort=source.reasoning_effort,
        )
    normalized = validate_and_normalize(
        profile_id=source.profile_id,
        temperature=source.temperature,
        top_p=source.top_p,
        max_tokens=source.max_tokens,
        reasoning_effort=source.reasoning_effort,
    )
    apply_runtime_settings(
        profile_id=normalized["profile_id"],
        temperature=normalized["temperature"],
        top_p=normalized["top_p"],
        max_tokens=int(normalized["max_tokens"]),
        reasoning_effort=normalized["reasoning_effort"],
    )
    await refresh_prompt_runtime_cache(session)
    return True


async def save_runtime_settings(
    session: AsyncSession,
    *,
    profile_id: str,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int,
    reasoning_effort: str | None,
) -> LlmRuntimeSettings:
    normalized = validate_and_normalize(
        profile_id=profile_id,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    row = await session.get(LlmRuntimeSettings, SINGLETON_ID)
    now = datetime.now(timezone.utc)
    if row is None:
        row = LlmRuntimeSettings(
            id=SINGLETON_ID,
            profile_id=normalized["profile_id"],
            temperature=normalized["temperature"],
            top_p=normalized["top_p"],
            max_tokens=int(normalized["max_tokens"]),
            reasoning_effort=normalized["reasoning_effort"],
            updated_at=now,
        )
        session.add(row)
    else:
        row.profile_id = normalized["profile_id"]
        row.temperature = normalized["temperature"]
        row.top_p = normalized["top_p"]
        row.max_tokens = int(normalized["max_tokens"])
        row.reasoning_effort = normalized["reasoning_effort"]
        row.updated_at = now
    await _write_default_from_values(
        session,
        profile_id=normalized["profile_id"],
        temperature=normalized["temperature"],
        top_p=normalized["top_p"],
        max_tokens=int(normalized["max_tokens"]),
        reasoning_effort=normalized["reasoning_effort"],
    )
    await session.commit()
    await session.refresh(row)
    apply_runtime_settings(
        profile_id=normalized["profile_id"],
        temperature=normalized["temperature"],
        top_p=normalized["top_p"],
        max_tokens=int(normalized["max_tokens"]),
        reasoning_effort=normalized["reasoning_effort"],
    )
    await refresh_prompt_runtime_cache(session)
    return row


async def get_or_none(session: AsyncSession) -> LlmRuntimeSettings | None:
    return await session.scalar(
        select(LlmRuntimeSettings).where(LlmRuntimeSettings.id == SINGLETON_ID)
    )


def runtime_view_from_normalized(normalized: dict[str, Any]) -> LlmRuntimeView:
    profile = get_profile(normalized["profile_id"])
    if profile.provider == "cerebras":
        api_key = settings.cerebras_api_key
        base_url = settings.cerebras_base_url
    elif profile.provider == "deepseek":
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
    else:
        raise ValueError(f"unknown LLM provider: {profile.provider}")
    return LlmRuntimeView(
        provider=profile.provider,
        model=profile.model,
        temperature=normalized["temperature"],
        top_p=normalized["top_p"],
        max_tokens=int(normalized["max_tokens"]),
        reasoning_effort=normalized["reasoning_effort"],
        api_key=api_key,
        base_url=base_url,
    )


def configuration_as_dict(row: LlmConfiguration) -> dict[str, Any]:
    profile = get_profile(row.profile_id)
    return {
        "id": row.id,
        "name": row.name,
        "profile_id": profile.id,
        "provider": profile.provider,
        "model": profile.model,
        "temperature": row.temperature,
        "top_p": row.top_p,
        "max_tokens": row.max_tokens,
        "reasoning_effort": row.reasoning_effort,
        "selection_role": row.selection_role,
        "capability_vision": bool(row.capability_vision),
        "capability_tools": bool(row.capability_tools),
        "capability_structured_output": bool(row.capability_structured_output),
        "capability_long_context": bool(row.capability_long_context),
        "enabled_for_auto": bool(row.enabled_for_auto),
        "priority": int(row.priority),
        "is_default": bool(row.is_default),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _apply_selection_metadata(row: LlmConfiguration, metadata: dict[str, Any]) -> None:
    row.selection_role = metadata["selection_role"]
    row.capability_vision = metadata["capability_vision"]
    row.capability_tools = metadata["capability_tools"]
    row.capability_structured_output = metadata["capability_structured_output"]
    row.capability_long_context = metadata["capability_long_context"]
    row.enabled_for_auto = metadata["enabled_for_auto"]
    row.priority = metadata["priority"]


def _normalize_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("name is required")
    if len(trimmed) > 128:
        raise ValueError("name must be at most 128 characters")
    return trimmed


async def list_configurations(session: AsyncSession) -> list[LlmConfiguration]:
    result = await session.execute(
        select(LlmConfiguration).order_by(
            LlmConfiguration.is_default.desc(),
            LlmConfiguration.name.asc(),
        )
    )
    return list(result.scalars().all())


async def get_default_configuration(session: AsyncSession) -> LlmConfiguration | None:
    return await session.scalar(
        select(LlmConfiguration)
        .where(LlmConfiguration.is_default.is_(True))
        .order_by(LlmConfiguration.id.asc())
        .limit(1)
    )


async def get_configuration(session: AsyncSession, configuration_id: int) -> LlmConfiguration:
    row = await session.get(LlmConfiguration, configuration_id)
    if row is None:
        raise LookupError("LLM configuration not found")
    return row


def assignment_as_dict(field: PromptField) -> dict[str, Any]:
    mode = field.llm_selection_mode if field.llm_selection_mode in SELECTION_MODES else "default"
    return {
        "llm_selection_mode": mode,
        "llm_configuration_id": field.llm_configuration_id,
    }


async def assignment_map(session: AsyncSession) -> dict[str, dict[str, Any]]:
    result = await session.execute(select(PromptField))
    assignments: dict[str, dict[str, Any]] = {}
    for field in result.scalars().all():
        mode = field.llm_selection_mode if field.llm_selection_mode in SELECTION_MODES else "default"
        if mode == "default" and field.llm_configuration_id is None:
            continue
        assignments[field.key] = assignment_as_dict(field)
    return assignments


def _cached_from_row(row: LlmConfiguration) -> CachedLlmConfiguration:
    normalized = validate_and_normalize(
        profile_id=row.profile_id,
        temperature=row.temperature,
        top_p=row.top_p,
        max_tokens=row.max_tokens,
        reasoning_effort=row.reasoning_effort,
    )
    metadata = normalize_selection_metadata(
        profile_id=normalized["profile_id"],
        selection_role=row.selection_role,
        capability_vision=row.capability_vision,
        capability_tools=row.capability_tools,
        capability_structured_output=row.capability_structured_output,
        capability_long_context=row.capability_long_context,
        enabled_for_auto=row.enabled_for_auto,
        priority=row.priority,
    )
    return CachedLlmConfiguration(
        id=row.id,
        name=row.name,
        is_default=bool(row.is_default),
        selection_role=cast(SelectionRole, metadata["selection_role"]),
        capability_vision=bool(metadata["capability_vision"]),
        capability_tools=bool(metadata["capability_tools"]),
        capability_structured_output=bool(metadata["capability_structured_output"]),
        capability_long_context=bool(metadata["capability_long_context"]),
        enabled_for_auto=bool(metadata["enabled_for_auto"]),
        priority=int(metadata["priority"]),
        view=runtime_view_from_normalized(normalized),
    )


async def refresh_prompt_runtime_cache(session: AsyncSession) -> None:
    rows = await list_configurations(session)
    configs = {row.id: _cached_from_row(row) for row in rows}
    default = next((row for row in rows if row.is_default), None)
    fields = (await session.execute(select(PromptField))).scalars().all()
    assignments: dict[str, PromptLlmAssignmentView] = {}
    for field in fields:
        mode: SelectionMode = (
            cast(SelectionMode, field.llm_selection_mode)
            if field.llm_selection_mode in SELECTION_MODES
            else "default"
        )
        if mode == "default" and field.llm_configuration_id is None:
            continue
        assignments[field.key] = PromptLlmAssignmentView(
            mode=mode,
            configuration_id=field.llm_configuration_id,
            allowed_configuration_ids=None,
        )
    set_runtime_selection_cache(
        assignments=assignments,
        configurations=configs,
        default_configuration_id=default.id if default is not None else None,
    )


async def _clear_other_defaults(session: AsyncSession, keep_id: int | None) -> None:
    stmt = select(LlmConfiguration).where(LlmConfiguration.is_default.is_(True))
    if keep_id is not None:
        stmt = stmt.where(LlmConfiguration.id != keep_id)
    for other in (await session.execute(stmt)).scalars().all():
        other.is_default = False
        other.updated_at = utcnow()


async def _write_default_from_values(
    session: AsyncSession,
    *,
    profile_id: str,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int,
    reasoning_effort: str | None,
) -> LlmConfiguration:
    normalized = validate_and_normalize(
        profile_id=profile_id,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    row = await get_default_configuration(session)
    now = utcnow()
    metadata = default_selection_metadata(normalized["profile_id"])
    if row is None:
        row = LlmConfiguration(
            name=DEFAULT_CONFIGURATION_NAME,
            profile_id=normalized["profile_id"],
            temperature=normalized["temperature"],
            top_p=normalized["top_p"],
            max_tokens=int(normalized["max_tokens"]),
            reasoning_effort=normalized["reasoning_effort"],
            selection_role=metadata["selection_role"],
            capability_vision=metadata["capability_vision"],
            capability_tools=metadata["capability_tools"],
            capability_structured_output=metadata["capability_structured_output"],
            capability_long_context=metadata["capability_long_context"],
            enabled_for_auto=metadata["enabled_for_auto"],
            priority=metadata["priority"],
            is_default=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.profile_id = normalized["profile_id"]
        row.temperature = normalized["temperature"]
        row.top_p = normalized["top_p"]
        row.max_tokens = int(normalized["max_tokens"])
        row.reasoning_effort = normalized["reasoning_effort"]
        if row.capability_vision and not metadata["capability_vision"]:
            row.capability_vision = False
        row.updated_at = now
    return row


async def _upsert_default_from_values(
    session: AsyncSession,
    *,
    profile_id: str,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int,
    reasoning_effort: str | None,
) -> LlmConfiguration:
    row = await _write_default_from_values(
        session,
        profile_id=profile_id,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    await session.commit()
    await session.refresh(row)
    return row


async def _sync_singleton_from_configuration(
    session: AsyncSession, row: LlmConfiguration
) -> None:
    now = utcnow()
    singleton = await session.get(LlmRuntimeSettings, SINGLETON_ID)
    if singleton is None:
        session.add(
            LlmRuntimeSettings(
                id=SINGLETON_ID,
                profile_id=row.profile_id,
                temperature=row.temperature,
                top_p=row.top_p,
                max_tokens=row.max_tokens,
                reasoning_effort=row.reasoning_effort,
                updated_at=now,
            )
        )
        return
    singleton.profile_id = row.profile_id
    singleton.temperature = row.temperature
    singleton.top_p = row.top_p
    singleton.max_tokens = row.max_tokens
    singleton.reasoning_effort = row.reasoning_effort
    singleton.updated_at = now


async def _apply_if_default(row: LlmConfiguration) -> None:
    if not row.is_default:
        return
    apply_runtime_settings(
        profile_id=row.profile_id,
        temperature=row.temperature,
        top_p=row.top_p,
        max_tokens=int(row.max_tokens),
        reasoning_effort=row.reasoning_effort,
    )


async def create_configuration(
    session: AsyncSession,
    *,
    name: str,
    profile_id: str,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    reasoning_effort: str | None,
    is_default: bool = False,
    selection_role: str | None = None,
    capability_vision: bool | None = None,
    capability_tools: bool | None = None,
    capability_structured_output: bool | None = None,
    capability_long_context: bool | None = None,
    enabled_for_auto: bool | None = None,
    priority: int | None = None,
) -> LlmConfiguration:
    normalized = validate_and_normalize(
        profile_id=profile_id,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    metadata = normalize_selection_metadata(
        profile_id=normalized["profile_id"],
        selection_role=selection_role,
        capability_vision=capability_vision,
        capability_tools=capability_tools,
        capability_structured_output=capability_structured_output,
        capability_long_context=capability_long_context,
        enabled_for_auto=enabled_for_auto,
        priority=priority,
    )
    existing = await list_configurations(session)
    make_default = is_default or not existing
    now = utcnow()
    row = LlmConfiguration(
        name=_normalize_name(name),
        profile_id=normalized["profile_id"],
        temperature=normalized["temperature"],
        top_p=normalized["top_p"],
        max_tokens=int(normalized["max_tokens"]),
        reasoning_effort=normalized["reasoning_effort"],
        selection_role=metadata["selection_role"],
        capability_vision=metadata["capability_vision"],
        capability_tools=metadata["capability_tools"],
        capability_structured_output=metadata["capability_structured_output"],
        capability_long_context=metadata["capability_long_context"],
        enabled_for_auto=metadata["enabled_for_auto"],
        priority=metadata["priority"],
        is_default=make_default,
        created_at=now,
        updated_at=now,
    )
    if make_default:
        await _clear_other_defaults(session, keep_id=None)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(f"LLM configuration name already exists: {row.name}") from exc
    if make_default:
        await _sync_singleton_from_configuration(session, row)
    await session.commit()
    await session.refresh(row)
    await _apply_if_default(row)
    await refresh_prompt_runtime_cache(session)
    return row


async def update_configuration(
    session: AsyncSession,
    configuration_id: int,
    *,
    name: str | None = None,
    profile_id: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    selection_role: str | None = None,
    capability_vision: bool | None = None,
    capability_tools: bool | None = None,
    capability_structured_output: bool | None = None,
    capability_long_context: bool | None = None,
    enabled_for_auto: bool | None = None,
    priority: int | None = None,
) -> LlmConfiguration:
    row = await get_configuration(session, configuration_id)
    normalized = validate_and_normalize(
        profile_id=profile_id if profile_id is not None else row.profile_id,
        temperature=row.temperature if temperature is None else temperature,
        top_p=row.top_p if top_p is None else top_p,
        max_tokens=row.max_tokens if max_tokens is None else max_tokens,
        reasoning_effort=row.reasoning_effort if reasoning_effort is None else reasoning_effort,
    )
    metadata = normalize_selection_metadata(
        profile_id=normalized["profile_id"],
        selection_role=row.selection_role if selection_role is None else selection_role,
        capability_vision=(
            row.capability_vision if capability_vision is None else capability_vision
        ),
        capability_tools=row.capability_tools if capability_tools is None else capability_tools,
        capability_structured_output=(
            row.capability_structured_output
            if capability_structured_output is None
            else capability_structured_output
        ),
        capability_long_context=(
            row.capability_long_context
            if capability_long_context is None
            else capability_long_context
        ),
        enabled_for_auto=(
            row.enabled_for_auto if enabled_for_auto is None else enabled_for_auto
        ),
        priority=row.priority if priority is None else priority,
    )
    if name is not None:
        row.name = _normalize_name(name)
    row.profile_id = normalized["profile_id"]
    row.temperature = normalized["temperature"]
    row.top_p = normalized["top_p"]
    row.max_tokens = int(normalized["max_tokens"])
    row.reasoning_effort = normalized["reasoning_effort"]
    _apply_selection_metadata(row, metadata)
    row.updated_at = utcnow()
    if row.is_default:
        await _sync_singleton_from_configuration(session, row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(f"LLM configuration name already exists: {row.name}") from exc
    await session.refresh(row)
    await _apply_if_default(row)
    await refresh_prompt_runtime_cache(session)
    return row


async def set_default_configuration(
    session: AsyncSession, configuration_id: int
) -> LlmConfiguration:
    row = await get_configuration(session, configuration_id)
    await _clear_other_defaults(session, keep_id=row.id)
    row.is_default = True
    row.updated_at = utcnow()
    assigned = (
        await session.execute(
            select(PromptField).where(PromptField.llm_configuration_id == row.id)
        )
    ).scalars().all()
    now = utcnow()
    for field in assigned:
        field.llm_configuration_id = None
        if field.llm_selection_mode == "fixed":
            field.llm_selection_mode = "default"
        field.updated_at = now
    await _sync_singleton_from_configuration(session, row)
    await session.commit()
    await session.refresh(row)
    apply_runtime_settings(
        profile_id=row.profile_id,
        temperature=row.temperature,
        top_p=row.top_p,
        max_tokens=int(row.max_tokens),
        reasoning_effort=row.reasoning_effort,
    )
    await refresh_prompt_runtime_cache(session)
    return row


async def delete_configuration(session: AsyncSession, configuration_id: int) -> None:
    row = await get_configuration(session, configuration_id)
    if row.is_default:
        raise ValueError("cannot delete the default LLM configuration")
    remaining = await list_configurations(session)
    if len(remaining) <= 1:
        raise ValueError("cannot delete the last LLM configuration")
    await session.delete(row)
    await session.commit()
    await refresh_prompt_runtime_cache(session)


async def assign_prompt_configuration(
    session: AsyncSession,
    prompt_key: str,
    configuration_id: int | None,
    selection_mode: SelectionMode | None = None,
) -> None:
    field = await session.scalar(select(PromptField).where(PromptField.key == prompt_key))
    if field is None:
        raise LookupError(f"unknown prompt key: {prompt_key}")
    mode: SelectionMode
    if selection_mode is None:
        mode = "default" if configuration_id is None else "fixed"
    else:
        if selection_mode not in SELECTION_MODES:
            raise ValueError(f"llm_selection_mode must be one of {list(SELECTION_MODES)}")
        mode = selection_mode
    if mode == "default":
        field.llm_selection_mode = "default"
        field.llm_configuration_id = None
    elif mode == "auto":
        field.llm_selection_mode = "auto"
        if configuration_id is None:
            field.llm_configuration_id = None
        else:
            config = await get_configuration(session, configuration_id)
            field.llm_configuration_id = None if config.is_default else config.id
    else:
        if configuration_id is None:
            raise ValueError("llm_configuration_id is required when mode is fixed")
        config = await get_configuration(session, configuration_id)
        if config.is_default:
            field.llm_selection_mode = "default"
            field.llm_configuration_id = None
        else:
            field.llm_selection_mode = "fixed"
            field.llm_configuration_id = config.id
    field.updated_at = utcnow()
    await session.commit()
    await refresh_prompt_runtime_cache(session)

