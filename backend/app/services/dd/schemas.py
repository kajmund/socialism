"""Pydantic schemas for DD sourcing and campaigns."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


DdResultatFilter = Literal["vinst", "förlust", "oavsett"]


class DdSourcingCriteria(BaseModel):
    alder_min: int = Field(ge=0, le=200, default=0)
    alder_max: int = Field(ge=0, le=200, default=100)
    omrade: str = ""
    resultat: DdResultatFilter = "oavsett"
    fritext: str = ""

    @field_validator("omrade", "fritext", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @model_validator(mode="after")
    def validate_age_range(self) -> "DdSourcingCriteria":
        if self.alder_min > self.alder_max:
            raise ValueError("alder_min must be <= alder_max")
        return self


class DdCandidateCompany(BaseModel):
    """Stable contract for allabolag.se integration (mock or real)."""

    id: str
    namn: str
    organisationsnummer: str
    alder_ar: int
    omrade: str
    resultat: DdResultatFilter
    omsattning_sek: int | None = None
    anstallda: int | None = None
    beskrivning: str = ""


DdCampaignStatus = Literal["draft", "sourcing", "ready", "running", "done", "failed"]


class DdCampaignCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    module: str = Field(default="dd", min_length=1, max_length=32)
    criteria: DdSourcingCriteria | None = None


class DdCampaignUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: DdCampaignStatus | None = None
    criteria: DdSourcingCriteria | None = None
    candidates: list[DdCandidateCompany] | None = None
    selected_candidate_ids: list[str] | None = None
    expert_role_keys: list[str] | None = None
    expert_panel_id: int | None = None


class DdCandidateRunOut(BaseModel):
    candidate_id: str
    panel_session_id: str | None = None
    report_id: str | None = None


class DdCampaignOut(BaseModel):
    id: int
    module: str
    title: str
    status: DdCampaignStatus
    criteria: DdSourcingCriteria
    candidates: list[DdCandidateCompany]
    selected_candidate_ids: list[str]
    expert_role_keys: list[str]
    expert_panel_id: int | None = None
    customer_id: int
    candidate_runs: list[DdCandidateRunOut] = Field(default_factory=list)
    created_at: str
    updated_at: str


class DdSourcingSearchRequest(BaseModel):
    criteria: DdSourcingCriteria


class DdSourcingSearchResponse(BaseModel):
    candidates: list[DdCandidateCompany]
