"""Pydantic schemas for panel sessions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


PanelProtocol = Literal["generic_panel"]
PanelSessionStatus = Literal["draft", "pending", "running", "succeeded", "failed"]
PanelTurnPhase = Literal["opening", "raise_hand", "expert", "scratchpad", "analysis"]


class PanelExpertSlot(BaseModel):
    slot_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=255)
    profile: str = ""


class PanelSessionConfig(BaseModel):
    protocol: PanelProtocol = "generic_panel"
    topic: str = Field(min_length=1, max_length=4000)
    brief: str = ""
    expert_slots: list[PanelExpertSlot] = Field(min_length=1, max_length=6)
    max_rounds: int = Field(default=2, ge=1, le=5)
    campaign_id: int | None = None

    @field_validator("topic", "brief", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()


class PanelTurn(BaseModel):
    turn_id: str
    speaker: str
    phase: PanelTurnPhase
    content: str
    round_index: int | None = None
    slot_id: str | None = None


class PanelSessionCreate(BaseModel):
    config: PanelSessionConfig


class PanelSessionOut(BaseModel):
    id: str
    protocol: PanelProtocol
    status: PanelSessionStatus
    config: PanelSessionConfig
    transcript: list[PanelTurn]
    scratchpads: dict[str, str]
    analysis: str | None
    campaign_id: int | None
    job_id: str | None
    error: str | None
    created_at: str
    updated_at: str


class PanelSessionRunJobRequest(BaseModel):
    session_id: str
