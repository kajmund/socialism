"""Pydantic schemas for panel sessions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.dd.schemas import DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge

PanelProtocol = Literal["generic_panel", "dd_panel"]
PanelSessionStatus = Literal["draft", "pending", "running", "succeeded", "failed"]
PanelTurnPhase = Literal[
    "opening",
    "raise_hand",
    "expert",
    "scratchpad",
    "analysis",
    "sub_question",
    "score",
]


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
    candidate: DdCandidateCompany | None = None
    candidate_id: str | None = None
    expert_role_keys: list[str] = Field(default_factory=list)

    @field_validator("topic", "brief", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @model_validator(mode="after")
    def validate_protocol_fields(self) -> "PanelSessionConfig":
        if self.protocol == "dd_panel":
            if self.candidate is None:
                raise ValueError("dd_panel requires candidate")
            if not self.candidate_id:
                self.candidate_id = self.candidate.id
        return self


class PanelTurn(BaseModel):
    turn_id: str
    speaker: str
    phase: PanelTurnPhase
    content: str
    round_index: int | None = None
    slot_id: str | None = None
    sub_question_id: str | None = None


class DdExpertScore(BaseModel):
    expert_slot_id: str
    expert_label: str
    sub_question_id: str
    sub_question_label: str
    score: int = Field(ge=1, le=10)
    motivation: str
    source: SourceBadge


class DdDissensusNote(BaseModel):
    sub_question_id: str
    sub_question_label: str
    min_score: int
    max_score: int
    spread: int


class DdPanelResult(BaseModel):
    protocol: Literal["dd_panel"] = "dd_panel"
    candidate: DdCandidateCompany
    scores: list[DdExpertScore]
    dissensus: list[DdDissensusNote]
    summary: str


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
    result: DdPanelResult | None = None
    campaign_id: int | None
    job_id: str | None
    error: str | None
    created_at: str
    updated_at: str


class PanelSessionRunJobRequest(BaseModel):
    session_id: str


class DdPanelSessionCreateRequest(BaseModel):
    campaign_id: int
    candidate_id: str
    expert_role_keys: list[str] | None = None
