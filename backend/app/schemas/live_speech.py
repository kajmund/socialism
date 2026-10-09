"""Validated control-plane contracts for the Live Speech WebSocket."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _ControlEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str


class SessionStart(_ControlEvent):
    type: Literal["session.start"]
    workspace_id: str = Field(min_length=1, max_length=64)
    expert_id: str = Field(min_length=1, max_length=64)
    language: Literal["sv", "en", "nb"] = "sv"
    client_request_id: str = Field(min_length=1, max_length=64)


class AudioStart(_ControlEvent):
    type: Literal["audio.start"]
    sequence: int = Field(ge=0)
    codec: Literal["pcm16"] = "pcm16"
    sample_rate: Literal[24000] = 24000
    channels: Literal[1] = 1


class AudioCommit(_ControlEvent):
    type: Literal["audio.commit"]
    input_item_id: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=0)


class AudioCancel(_ControlEvent):
    type: Literal["audio.cancel"]
    turn_id: str | None = Field(default=None, max_length=64)


class TurnCancel(_ControlEvent):
    type: Literal["turn.cancel"]
    turn_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=64)


class SessionMute(_ControlEvent):
    type: Literal["session.mute"]
    muted: bool


class SessionStop(_ControlEvent):
    type: Literal["session.stop"]
    reason: str = Field(min_length=1, max_length=64)


class ClientPing(_ControlEvent):
    type: Literal["client.ping"]
    sequence: int = Field(ge=0)


ClientControl = Annotated[
    SessionStart
    | AudioStart
    | AudioCommit
    | AudioCancel
    | TurnCancel
    | SessionMute
    | SessionStop
    | ClientPing,
    Field(discriminator="type"),
]

client_control_adapter = TypeAdapter(ClientControl)
