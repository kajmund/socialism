"""List live voices and reject a Gemini voice the provider does not offer."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import settings
from app.database.models import Persona, UserAccount
from app.database.session import get_session
from app.schemas.live_voice import LiveVoiceOption
from app.services.elevenlabs_live import list_elevenlabs_voices
from app.services.live_voice import (
    GEMINI_LIVE_VOICES,
    LiveVoiceProviderError,
    LiveVoiceUnavailable,
    expert_live_voice,
)
from app.services.live_voice_tools import live_voice_tool_specs


def register_live_voices(router: APIRouter) -> None:
    router.add_api_route(
        "/live-voices",
        list_live_voices,
        methods=["GET"],
        response_model=list[LiveVoiceOption],
    )


async def list_live_voices(
    provider: str = Query(pattern="^(gemini|elevenlabs)$"),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[LiveVoiceOption]:
    del user
    await session.rollback()
    if provider == "gemini":
        return [LiveVoiceOption(id=name, name=name) for name in GEMINI_LIVE_VOICES]
    try:
        return [LiveVoiceOption(**row) for row in await list_elevenlabs_voices()]
    except LiveVoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LiveVoiceProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def reject_unknown_gemini_voice(data: dict, persona: Persona) -> None:
    provider = data.get("live_voice_provider", persona.live_voice_provider) or settings.live_voice_provider
    voice = data["live_voice"] if "live_voice" in data else persona.live_voice
    if provider == "gemini" and voice and voice not in GEMINI_LIVE_VOICES:
        raise HTTPException(status_code=422, detail="unknown_gemini_voice")


def persona_update_data(persona: Persona, data: dict) -> dict:
    reject_unknown_gemini_voice(data, persona)
    return data


def voice_for_token(persona: Persona) -> tuple[str, str, list[dict]]:
    """Read the saved voice and tool specs before the request session is closed."""
    specs = live_voice_tool_specs(persona)
    try:
        provider, voice = expert_live_voice(persona)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return provider, voice, specs
