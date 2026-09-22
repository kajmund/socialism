"""Per-call LLM settings via ContextVar. Process defaults stay on ``settings``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

from app.config import settings

SelectionMode = Literal["default", "fixed", "auto"]
SelectionRole = Literal["fast", "balanced", "deep"]
LLMCallKind = Literal["structured", "text", "stream", "tools"]


@dataclass(frozen=True)
class LlmRuntimeView:
    provider: str
    model: str
    temperature: float | None
    top_p: float | None
    max_tokens: int
    reasoning_effort: str | None
    api_key: str
    base_url: str


@dataclass(frozen=True)
class PromptLlmAssignmentView:
    mode: SelectionMode
    configuration_id: int | None
    allowed_configuration_ids: tuple[int, ...] | None = None


@dataclass(frozen=True)
class CachedLlmConfiguration:
    id: int
    name: str
    is_default: bool
    selection_role: SelectionRole
    capability_vision: bool
    capability_tools: bool
    capability_structured_output: bool
    capability_long_context: bool
    enabled_for_auto: bool
    priority: int
    view: LlmRuntimeView


@dataclass(frozen=True)
class LlmResolution:
    view: LlmRuntimeView
    prompt_key: str | None
    selection_mode: SelectionMode
    selected_configuration_id: int | None
    auto_confidence: float | None
    reason_code: str
    fallback: bool
    call_kind: LLMCallKind
    speed_class: SelectionRole | None = None


_runtime_override: ContextVar[LlmRuntimeView | None] = ContextVar(
    "llm_runtime_override", default=None
)
_resolution: ContextVar[LlmResolution | None] = ContextVar(
    "llm_runtime_resolution", default=None
)
_retry_flag: ContextVar[bool] = ContextVar("llm_runtime_retry", default=False)
_prompt_views: dict[str, LlmRuntimeView] = {}
_assignments: dict[str, PromptLlmAssignmentView] = {}
_configurations: dict[int, CachedLlmConfiguration] = {}
_default_configuration_id: int | None = None


def settings_runtime_view() -> LlmRuntimeView:
    return LlmRuntimeView(
        provider=settings.llm_provider,
        model=settings.selected_llm_model,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        max_tokens=settings.llm_max_tokens,
        reasoning_effort=settings.selected_reasoning_effort,
        api_key=settings.selected_llm_api_key,
        base_url=settings.selected_llm_base_url,
    )


def current_runtime() -> LlmRuntimeView:
    override = _runtime_override.get()
    if override is not None:
        return override
    return settings_runtime_view()


def current_resolution() -> LlmResolution | None:
    return _resolution.get()


def current_retry() -> bool:
    return _retry_flag.get()


def set_prompt_runtime_views(views: dict[str, LlmRuntimeView]) -> None:
    global _prompt_views
    _prompt_views = dict(views)


def set_runtime_selection_cache(
    *,
    assignments: dict[str, PromptLlmAssignmentView],
    configurations: dict[int, CachedLlmConfiguration],
    default_configuration_id: int | None,
) -> None:
    global _assignments, _configurations, _default_configuration_id
    _assignments = dict(assignments)
    _configurations = dict(configurations)
    _default_configuration_id = default_configuration_id
    views: dict[str, LlmRuntimeView] = {}
    for key, assignment in _assignments.items():
        if assignment.mode != "fixed" or assignment.configuration_id is None:
            continue
        row = _configurations.get(assignment.configuration_id)
        if row is None or row.is_default:
            continue
        views[key] = row.view
    set_prompt_runtime_views(views)


def assignment_for_prompt(prompt_key: str | None) -> PromptLlmAssignmentView:
    if not prompt_key:
        return PromptLlmAssignmentView(mode="default", configuration_id=None)
    return _assignments.get(
        prompt_key, PromptLlmAssignmentView(mode="default", configuration_id=None)
    )


def cached_configurations() -> dict[int, CachedLlmConfiguration]:
    return dict(_configurations)


def default_configuration() -> CachedLlmConfiguration | None:
    if _default_configuration_id is None:
        return None
    return _configurations.get(_default_configuration_id)


def view_for_prompt(prompt_key: str | None) -> LlmRuntimeView | None:
    if not prompt_key:
        return None
    return _prompt_views.get(prompt_key)


def bind_llm_runtime(view: LlmRuntimeView | None) -> Token[LlmRuntimeView | None]:
    return _runtime_override.set(view)


def reset_llm_runtime(token: Token[LlmRuntimeView | None]) -> None:
    _runtime_override.reset(token)


def bind_llm_resolution(resolution: LlmResolution | None) -> Token[LlmResolution | None]:
    return _resolution.set(resolution)


def reset_llm_resolution(token: Token[LlmResolution | None]) -> None:
    _resolution.reset(token)


def bind_llm_retry(retry: bool) -> Token[bool]:
    return _retry_flag.set(retry)


def reset_llm_retry(token: Token[bool]) -> None:
    _retry_flag.reset(token)


@contextmanager
def bound_llm_runtime(view: LlmRuntimeView | None) -> Iterator[None]:
    if view is None:
        yield
        return
    token = bind_llm_runtime(view)
    try:
        yield
    finally:
        reset_llm_runtime(token)


@contextmanager
def bound_llm_prompt(prompt_key: str | None) -> Iterator[None]:
    with bound_llm_runtime(view_for_prompt(prompt_key)):
        yield


@contextmanager
def bound_llm_resolution(resolution: LlmResolution | None) -> Iterator[None]:
    if resolution is None:
        yield
        return
    token = bind_llm_resolution(resolution)
    try:
        yield
    finally:
        reset_llm_resolution(token)


@contextmanager
def bound_llm_retry(retry: bool) -> Iterator[None]:
    token = bind_llm_retry(retry)
    try:
        yield
    finally:
        reset_llm_retry(token)
