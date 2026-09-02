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
    def validate_age_range(self) -> DdSourcingCriteria:
        if self.alder_min > self.alder_max:
            raise ValueError("alder_min must be <= alder_max")
        return self


class DdAccountFigure(BaseModel):
    kod: str
    namn: str
    enhet: Literal["sek", "pct", "antal", "tal"] = "sek"
    sek: int | None = None
    tal: str | None = None


class DdAccountYear(BaseModel):
    year: str
    omsattning_sek: int | None = None
    resultat_sek: int | None = None
    ebitda_sek: int | None = None
    utdelning_sek: int | None = None
    anstallda: int | None = None
    eget_kapital_sek: int | None = None
    soliditet_pct: str | None = None
    poster: list[DdAccountFigure] = Field(default_factory=list)


class DdOfficer(BaseModel):
    namn: str
    roll: str
    grupp: str = ""


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
    fskatt: bool | None = None
    moms: bool | None = None
    arbetsgivaravgift: bool | None = None
    styrelse: list[DdOfficer] = Field(default_factory=list)
    firmateckning: list[str] = Field(default_factory=list)
    koncern_bolag: int | None = None
    koncern_dotter: int | None = None
    moderbolag: str = ""
    varumarken: list[str] = Field(default_factory=list)
    rakenskaper: list[DdAccountYear] = Field(default_factory=list)
    sni: list[str] = Field(default_factory=list)
    handelser: list[str] = Field(default_factory=list)
    arbetsstallen: list[str] = Field(default_factory=list)
    relaterade_bolag: list[str] = Field(default_factory=list)
    telefon: str = ""
    foretagshypotek: bool | None = None
    betalningsanmarkning: bool | None = None
    gasell: bool | None = None


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
    panel_assignments: dict[str, int] | None = None
    enrich_from_allabolag: bool = False


DdResearchMode = Literal["group", "people"]
DdResearchRelation = Literal["kandidat", "moderbolag", "dotterbolag"]


class DdResearchCompany(BaseModel):
    namn: str
    orgnr: str = ""
    parent_orgnr: str = ""
    relation: DdResearchRelation
    nyckeltal: list[str] = Field(default_factory=list)
    styrelse: list[str] = Field(default_factory=list)


class DdResearchPersonSeat(BaseModel):
    namn: str
    orgnr: str = ""
    roll: str = ""


class DdResearchPersonCompany(BaseModel):
    namn: str
    orgnr: str = ""


class DdResearchWebHit(BaseModel):
    title: str = ""
    url: str = ""
    natverk: str = ""


class DdResearchPerson(BaseModel):
    namn: str
    roll: str = ""
    poster: list[DdResearchPersonSeat] = Field(default_factory=list)
    bolag: list[DdResearchPersonCompany] = Field(default_factory=list)
    web_hits: list[DdResearchWebHit] = Field(default_factory=list)


class DdResearchPending(BaseModel):
    orgnr: str
    namn: str = ""


class DdResearchDossier(BaseModel):
    companies: list[DdResearchCompany] = Field(default_factory=list)
    people: list[DdResearchPerson] = Field(default_factory=list)
    leftover: list[str] = Field(default_factory=list)
    pending: list[DdResearchPending] = Field(default_factory=list)
    searched_names: list[str] = Field(default_factory=list)
    group_size: int | None = None
    job_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def drop_non_group_companies(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        companies = value.get("companies")
        if not isinstance(companies, list):
            return value
        allowed = {"kandidat", "moderbolag", "dotterbolag"}
        cleaned = dict(value)
        cleaned["companies"] = [
            row
            for row in companies
            if not isinstance(row, dict) or row.get("relation") in allowed
        ]
        return cleaned


class DdResearchStartRequest(BaseModel):
    mode: DdResearchMode = "group"
    person_names: list[str] = Field(default_factory=list)
    continue_group: bool = False


class DdResearchJobRequest(BaseModel):
    campaign_id: int
    candidate_id: str
    mode: DdResearchMode = "group"
    person_names: list[str] = Field(default_factory=list)
    continue_group: bool = False


class DdCandidateRunOut(BaseModel):
    candidate_id: str
    panel_session_id: str | None = None
    report_id: str | None = None
    research: DdResearchDossier | None = None
    research_job_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


class StoredObjectOut(BaseModel):
    id: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    campaign_id: int | None = None
    candidate_id: str | None = None
    report_id: str | None = None
    created_at: str = ""


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
    panel_assignments: dict[str, int] = Field(default_factory=dict)
    customer_id: int
    candidate_runs: list[DdCandidateRunOut] = Field(default_factory=list)
    created_at: str
    updated_at: str


class DdSourcingSearchRequest(BaseModel):
    criteria: DdSourcingCriteria


class DdSourcingSearchResponse(BaseModel):
    candidates: list[DdCandidateCompany]


class DdSourcingChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class DdSourcingChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[DdSourcingChatMessage] = Field(default_factory=list)


class DdSourcingChatResponse(BaseModel):
    reply: str
    candidates: list[DdCandidateCompany]
