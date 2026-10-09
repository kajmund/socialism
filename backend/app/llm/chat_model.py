"""Last resolved chat model, kept after the call so a trace can name it."""

from __future__ import annotations

from contextvars import ContextVar

from app.llm.runtime_override import LlmResolution, cached_configurations

_label: ContextVar[str] = ContextVar("chat_model_label", default="")


def remember_chat_model(resolution: LlmResolution | None) -> None:
    _label.set(chat_model_label(resolution))


def current_chat_model() -> str:
    return _label.get()


def chat_model_label(resolution: LlmResolution | None) -> str:
    if resolution is None:
        return ""
    config_name = _configuration_name(resolution.selected_configuration_id)
    model = resolution.view.model
    parts: list[str] = []
    if config_name and config_name != model:
        parts.append(config_name)
    if model:
        parts.append(model)
    if resolution.speed_class:
        parts.append(resolution.speed_class)
    return " · ".join(parts)


def _configuration_name(config_id: int | None) -> str:
    if config_id is None:
        return ""
    config = cached_configurations().get(config_id)
    if config is None:
        return ""
    return config.name
