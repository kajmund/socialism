"""Playground: persona reaction to an uploaded image + SSR mini-report."""

from __future__ import annotations

import time
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.llm.chat import reply_as_persona
from app.llm.vision import VisionRequest, complete_vision_text
from app.serializers import profile_from_dict
from app.services.district_context import area_block_for_name
from app.services.playground import rate_case
from app.services.playground_image_models import (
    resolve_reaction_model,
    resolve_vision_selection,
)
from app.services.prompt_store import require_prompts_for_persona
from app.services.sentiment_lexicon import classify_text

Locale = Literal["sv", "en"]

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


def validate_image(*, content_type: str | None, size_bytes: int) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_IMAGE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_TYPES))
        raise ValueError(f"Unsupported image type {mime!r} — allowed: {allowed}")
    if size_bytes <= 0:
        raise ValueError("Image file is empty")
    if size_bytes > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit")
    return mime


from app.services.image_caption import rich_caption_prompt


def _reaction_user_message(description: str, *, locale: Locale) -> str:
    if locale == "en":
        return (
            "You scroll your feed and stop at a post with this image:\n\n"
            f"{description}\n\n"
            "Write your immediate reaction — as if commenting or thinking aloud (2–4 sentences)."
        )
    return (
        "Du scrollar i ditt flöde och stannar vid ett inlägg med denna bild:\n\n"
        f"{description}\n\n"
        "Skriv din omedelbara reaktion — som om du skulle kommentera eller tänka högt (2–4 meningar)."
    )


def _ssr_slice(result: dict) -> dict:
    per_text = result["per_text"][0]
    return {
        "anchor_set_name": result["anchor_set_name"],
        "anchor_set_version": result["anchor_set_version"],
        "labels": result["labels"],
        "shares": result["shares"],
        "predicted_label": per_text["predicted_label"],
        "pmf": per_text["pmf"],
    }


async def react_to_image(
    session: AsyncSession,
    *,
    persona: Persona,
    image_bytes: bytes,
    content_type: str,
    locale: Locale = "sv",
    temperature: float = 0.1,
    vision_provider: str | None = None,
    vision_model: str | None = None,
    reaction_model: str | None = None,
) -> dict:
    started = time.perf_counter()
    mime = validate_image(content_type=content_type, size_bytes=len(image_bytes))
    provider, vision_model_id = resolve_vision_selection(
        provider=vision_provider,
        model=vision_model,
    )
    reaction_model_id = resolve_reaction_model(reaction_model)

    description = await complete_vision_text(
        image_bytes=image_bytes,
        content_type=mime,
        prompt=rich_caption_prompt(locale),
        provider=provider,
        model=vision_model_id,
    )
    profile = profile_from_dict(persona.profile, persona.name)
    area_block = await area_block_for_name(session, profile.ort or persona.district)
    prompts = await require_prompts_for_persona(session, persona, language=locale)
    reaction = await reply_as_persona(
        profile,
        "character",
        [],
        _reaction_user_message(description, locale=locale),
        prompts=prompts,
        area_block=area_block,
        model=reaction_model_id,
    )

    tone_result, style_result = await _rate_both(
        reaction,
        locale=locale,
        temperature=temperature,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "persona_id": persona.id,
        "persona_name": persona.name,
        "image_description": description,
        "reaction": reaction,
        "lexicon_label": classify_text(reaction),
        "locale": locale,
        "temperature": temperature,
        "vision_provider": provider,
        "vision_model": vision_model_id,
        "reaction_model": reaction_model_id,
        "ssr": {
            "tone": _ssr_slice(tone_result),
            "style": _ssr_slice(style_result),
        },
        "elapsed_ms": elapsed_ms,
    }


async def _rate_both(
    text: str,
    *,
    locale: Locale,
    temperature: float,
) -> tuple[dict, dict]:
    tone = await rate_case(
        [text],
        dimension="tone",
        locale=locale,
        labels=None,
        statements=None,
        temperature=temperature,
        human_labels=None,
    )
    style = await rate_case(
        [text],
        dimension="style",
        locale=locale,
        labels=None,
        statements=None,
        temperature=temperature,
        human_labels=None,
    )
    return tone, style
