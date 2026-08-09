"""Curated model catalog for playground image test bench."""

from __future__ import annotations

from typing import Literal, TypedDict

from app.config import settings

VisionProvider = Literal["openai", "google", "ollama"]

VISION_PROVIDERS: dict[VisionProvider, dict[str, object]] = {
    "openai": {
        "label": "OpenAI",
        "models": [
            {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
            {"id": "gpt-4o", "label": "GPT-4o"},
        ],
    },
    "google": {
        "label": "Google Gemini",
        "models": [
            {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        ],
    },
    "ollama": {
        "label": "Ollama Cloud",
        "models": [
            {"id": "qwen3.5:397b-cloud", "label": "Qwen 3.5 397B (vision)"},
            {"id": "gemma3:27b-cloud", "label": "Gemma 3 27B"},
        ],
    },
}

REACTION_MODELS: list[dict[str, str]] = [
    {"id": "deepseek-chat", "label": "DeepSeek Chat"},
    {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner"},
]


class VisionProviderOut(TypedDict):
    id: VisionProvider
    label: str
    available: bool
    unavailable_reason: str | None
    models: list[dict[str, str]]


def _provider_available(provider: VisionProvider) -> tuple[bool, str | None]:
    if provider == "openai":
        if settings.openai_api_key.strip():
            return True, None
        return False, "OPENAI_API_KEY saknas"
    if provider == "google":
        if settings.google_api_key.strip():
            return True, None
        return False, "GOOGLE_API_KEY saknas"
    if provider == "ollama":
        if settings.ollama_api_key.strip():
            return True, None
        return False, "OLLAMA_API_KEY saknas"
    return False, "Okänd leverantör"


def image_model_catalog() -> dict:
    providers: list[VisionProviderOut] = []
    for provider_id, meta in VISION_PROVIDERS.items():
        available, reason = _provider_available(provider_id)  # type: ignore[arg-type]
        providers.append(
            {
                "id": provider_id,  # type: ignore[typeddict-item]
                "label": str(meta["label"]),
                "available": available,
                "unavailable_reason": reason,
                "models": list(meta["models"]),  # type: ignore[arg-type]
            }
        )
    default_provider: VisionProvider = "openai"
    if not _provider_available("openai")[0]:
        for candidate in providers:
            if candidate["available"]:
                default_provider = candidate["id"]
                break
    default_vision_model = settings.vision_model
    openai_models = {str(row["id"]) for row in VISION_PROVIDERS["openai"]["models"]}  # type: ignore[index]
    if default_provider != "openai" or default_vision_model not in openai_models:
        default_vision_model = str(VISION_PROVIDERS[default_provider]["models"][0]["id"])  # type: ignore[index]
    return {
        "defaults": {
            "vision_provider": default_provider,
            "vision_model": default_vision_model,
            "reaction_model": settings.deepseek_model,
        },
        "vision_providers": providers,
        "reaction_models": REACTION_MODELS,
    }


def resolve_vision_selection(
    *,
    provider: str | None,
    model: str | None,
) -> tuple[VisionProvider, str]:
    catalog = image_model_catalog()
    chosen_provider = (provider or catalog["defaults"]["vision_provider"]).strip().lower()
    if chosen_provider not in VISION_PROVIDERS:
        allowed = ", ".join(VISION_PROVIDERS)
        raise ValueError(f"Unknown vision provider {chosen_provider!r} — allowed: {allowed}")

    available, reason = _provider_available(chosen_provider)  # type: ignore[arg-type]
    if not available:
        raise ValueError(reason or f"Vision provider {chosen_provider!r} is not configured")

    provider_models = VISION_PROVIDERS[chosen_provider]["models"]  # type: ignore[index]
    allowed_ids = {str(row["id"]) for row in provider_models}  # type: ignore[union-attr]
    if model and model.strip():
        chosen_model = model.strip()
    elif chosen_provider == "openai" and settings.vision_model in allowed_ids:
        chosen_model = settings.vision_model
    else:
        chosen_model = str(provider_models[0]["id"])  # type: ignore[index]
    if chosen_model not in allowed_ids:
        raise ValueError(
            f"Model {chosen_model!r} is not allowed for provider {chosen_provider!r}"
        )
    return chosen_provider, chosen_model  # type: ignore[return-value]


def resolve_reaction_model(model: str | None) -> str:
    chosen = (model or settings.deepseek_model).strip()
    allowed = {row["id"] for row in REACTION_MODELS}
    if chosen not in allowed:
        raise ValueError(f"Unknown reaction model {chosen!r} — allowed: {', '.join(sorted(allowed))}")
    return chosen
