"""Live-voice request and response models."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

LiveVoiceProviderName = Literal["gemini", "elevenlabs", "socialism", "openai"]


class LiveVoiceModelMixin:
    """Per-expert model for providers that offer one (OpenAI Realtime)."""

    live_voice_model: str | None = Field(default=None, max_length=64)

    @field_validator("live_voice_model")
    @classmethod
    def strip_live_voice_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class SttCorrectionMixin:
    """Per-expert STT-correction settings for Socialism live voice."""

    stt_correction_enabled: bool | None = None
    stt_correction_timeout_seconds: float | None = Field(default=None, ge=0.5, le=10)


class LiveVoiceOption(BaseModel):
    id: str
    name: str


class LiveVoiceAudioOut(BaseModel):
    input_format: str
    output_format: str


class PersonaLiveTokenOut(BaseModel):
    provider: LiveVoiceProviderName
    websocket_url: str
    model: str
    voice: str
    expires_at: str
    initial_turn: str
    audio: LiveVoiceAudioOut
    client_init: dict[str, Any] | None = None


class PersonaLiveMemoryRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    user_message: str = Field(min_length=1, max_length=20_000)
    assistant_message: str = Field(min_length=1, max_length=20_000)


class PersonaLiveToolHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class PersonaLiveToolRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    history: list[PersonaLiveToolHistoryItem] = Field(default_factory=list, max_length=50)
    user_message: str = Field(default="", max_length=20_000)


class PersonaLiveToolResponse(BaseModel):
    result: str
