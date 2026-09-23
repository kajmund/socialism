from typing import Any, Protocol

from httpx import AsyncClient

from app.config import settings
from app.schemas.domain import PersonaLiveTokenOut


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
        client: AsyncClient | None = None,
    ) -> PersonaLiveTokenOut: ...


def get_live_voice_provider() -> LiveVoiceProvider:
    """Return the configured live-voice mint adapter.

    Providers are imported here because they import exceptions from this module.
    """
    name = settings.live_voice_provider
    if name == "gemini":
        from app.services.gemini_live import GeminiLiveVoiceProvider

        return GeminiLiveVoiceProvider()
    if name == "elevenlabs":
        from app.services.elevenlabs_live import ElevenLabsLiveVoiceProvider

        return ElevenLabsLiveVoiceProvider()
    raise RuntimeError(f"unknown LIVE_VOICE_PROVIDER: {name}")


async def create_live_voice_session(
    system_instruction: str,
    *,
    initial_turn: str,
    tools: list[dict[str, Any]],
    client: AsyncClient | None = None,
) -> PersonaLiveTokenOut:
    provider = get_live_voice_provider()
    return await provider.create_session(
        system_instruction,
        initial_turn=initial_turn,
        tools=tools,
        client=client,
    )
