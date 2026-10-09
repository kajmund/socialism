from typing import Any, Protocol

from httpx import AsyncClient

from app.config import settings
from app.database.models import Persona
from app.schemas.domain import PersonaLiveTokenOut

# Gemini Live prebuilt voices. The name is the voice id.
GEMINI_LIVE_VOICES = (
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
)


class LiveVoiceUnavailable(RuntimeError):
    pass


class LiveVoiceProviderError(RuntimeError):
    pass


class LiveVoiceProvider(Protocol):
    async def create_session(
        self,
        system_instruction: str,
        *,
        initial_turn: str,
        tools: list[dict[str, Any]],
        voice: str | None = None,
        client: AsyncClient | None = None,
    ) -> PersonaLiveTokenOut: ...


def expert_live_voice(persona: Persona) -> tuple[str, str]:
    """Saved expert choice, or the process defaults from settings."""
    provider = persona.live_voice_provider or settings.live_voice_provider
    saved = (persona.live_voice or "").strip()
    if provider == "gemini":
        voice = saved or settings.gemini_live_voice
        if voice not in GEMINI_LIVE_VOICES:
            raise ValueError("unknown_gemini_voice")
        return provider, voice
    if provider in {"elevenlabs", "socialism"}:
        return provider, saved or settings.elevenlabs_voice_id.strip()
    raise RuntimeError(f"unknown LIVE_VOICE_PROVIDER: {provider}")


def get_live_voice_provider(name: str | None = None) -> LiveVoiceProvider:
    """Return the configured live-voice mint adapter.

    Providers are imported here because they import exceptions from this module.
    """
    chosen = name or settings.live_voice_provider
    if chosen == "gemini":
        from app.services.gemini_live import GeminiLiveVoiceProvider

        return GeminiLiveVoiceProvider()
    if chosen == "elevenlabs":
        from app.services.elevenlabs_live import ElevenLabsLiveVoiceProvider

        return ElevenLabsLiveVoiceProvider()
    if chosen == "socialism":
        raise LiveVoiceUnavailable("socialism_live_speech_workspace_required")
    raise RuntimeError(f"unknown LIVE_VOICE_PROVIDER: {chosen}")


async def create_live_voice_session(
    system_instruction: str,
    *,
    initial_turn: str,
    tools: list[dict[str, Any]],
    provider: str | None = None,
    voice: str | None = None,
    client: AsyncClient | None = None,
) -> PersonaLiveTokenOut:
    adapter = get_live_voice_provider(provider)
    return await adapter.create_session(
        system_instruction,
        initial_turn=initial_turn,
        tools=tools,
        voice=voice,
        client=client,
    )
