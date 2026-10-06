"""Live-voice request and response models."""

from typing import Any, Literal

from pydantic import BaseModel, Field

LiveVoiceProviderName = Literal["gemini", "elevenlabs"]


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
