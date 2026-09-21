"""Per-call LLM settings via ContextVar. Process defaults stay on ``settings``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

from app.config import settings


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


_runtime_override: ContextVar[LlmRuntimeView | None] = ContextVar(
    "llm_runtime_override", default=None
)
_prompt_views: dict[str, LlmRuntimeView] = {}


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


def set_prompt_runtime_views(views: dict[str, LlmRuntimeView]) -> None:
    global _prompt_views
    _prompt_views = dict(views)


def view_for_prompt(prompt_key: str | None) -> LlmRuntimeView | None:
    if not prompt_key:
        return None
    return _prompt_views.get(prompt_key)


def bind_llm_runtime(view: LlmRuntimeView | None) -> Token[LlmRuntimeView | None]:
    return _runtime_override.set(view)


def reset_llm_runtime(token: Token[LlmRuntimeView | None]) -> None:
    _runtime_override.reset(token)


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
