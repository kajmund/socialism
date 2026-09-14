"""Catalog + DB-backed override for the active chat LLM (admin Tools page)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLMProvider, settings
from app.database.models import LlmRuntimeSettings
from app.llm import reset_client

ProfileId = Literal[
    "deepseek-flash",
    "deepseek-v4-pro",
    "gpt-oss-120b",
    "qwen-3.8-27b",
]

SINGLETON_ID = 1

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
        supports_vision=True,
        allowed_image_types=_DEEPSEEK_IMAGE_TYPES,
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
    """Apply persisted row if present. Returns True when a row was applied."""
    row = await session.get(LlmRuntimeSettings, SINGLETON_ID)
    if row is None:
        return False
    normalized = validate_and_normalize(
        profile_id=row.profile_id,
        temperature=row.temperature,
        top_p=row.top_p,
        max_tokens=row.max_tokens,
        reasoning_effort=row.reasoning_effort,
    )
    apply_runtime_settings(
        profile_id=normalized["profile_id"],
        temperature=normalized["temperature"],
        top_p=normalized["top_p"],
        max_tokens=int(normalized["max_tokens"]),
        reasoning_effort=normalized["reasoning_effort"],
    )
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
    await session.commit()
    await session.refresh(row)
    apply_runtime_settings(
        profile_id=normalized["profile_id"],
        temperature=normalized["temperature"],
        top_p=normalized["top_p"],
        max_tokens=int(normalized["max_tokens"]),
        reasoning_effort=normalized["reasoning_effort"],
    )
    return row


async def get_or_none(session: AsyncSession) -> LlmRuntimeSettings | None:
    return await session.scalar(
        select(LlmRuntimeSettings).where(LlmRuntimeSettings.id == SINGLETON_ID)
    )
