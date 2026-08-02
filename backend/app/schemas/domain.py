from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PersonaOrigin = Literal["manuell", "beskrivning", "demografi", "population"]


class EditablePersona(BaseModel):
    name: str
    initials: str = "--"
    age: str = "—"
    ort: str = "—"
    yrke: str = "—"
    utbildning: str = "—"
    livssituation: str = "—"
    lutning: str = "—"
    sakfragor: str = "—"
    fortroende: str = "—"
    ton: str = "—"
    sprak: str = "—"
    medievanor: str = "—"
    parti: str = "—"
    valdeltagande: str = "—"


class LibraryPersona(BaseModel):
    id: str
    name: str
    age: int
    occ: str
    district: str
    quote: str
    pops: list[str]
    updated: str
    origin: PersonaOrigin


class PersonaDetail(LibraryPersona):
    profile: EditablePersona


class PersonaCreate(BaseModel):
    id: str | None = None
    name: str
    age: int
    occ: str
    district: str
    quote: str = ""
    origin: PersonaOrigin = "manuell"
    profile: EditablePersona | None = None


class PersonaUpdate(BaseModel):
    name: str | None = None
    age: int | None = None
    occ: str | None = None
    district: str | None = None
    quote: str | None = None
    origin: PersonaOrigin | None = None
    profile: EditablePersona | None = None


class PopulationMemberOut(BaseModel):
    member_id: int
    id: str | None = None
    name: str
    initials: str
    age: int
    occ: str
    district: str
    trait: str


class PopulationMemberCreate(BaseModel):
    persona_id: str | None = None
    name: str
    initials: str
    age: int
    occ: str
    district: str
    trait: str = ""


class DistRow(BaseModel):
    k: str
    l: str
    v: int


class DistGroup(BaseModel):
    label: str
    rows: list[DistRow]


class PopulationRecipe(BaseModel):
    size: int = Field(ge=1, le=40)
    entryMode: Literal["free", "manual"] = "manual"
    freeText: str = ""
    dist: dict[str, DistGroup]
    locale: str = "norrkoping"
    seed: int | None = None


class GeneratedPersonaOut(BaseModel):
    name: str
    initials: str
    age: int
    occ: str
    district: str
    occ_key: str = ""
    district_key: str = ""
    lean: str = "mitt"
    lean_label: str = "Mitt"
    trait: str = ""
    quote: str = ""
    profile: EditablePersona


class GenerationCandidate(BaseModel):
    key: str
    source: Literal["generated", "library"]
    persona_id: str | None = None
    persona: GeneratedPersonaOut


class PopulationGenerateRequest(BaseModel):
    recipe: PopulationRecipe
    include_persona_ids: list[str] = Field(default_factory=list)
    generation_id: str | None = None
    existing: list[GenerationCandidate] = Field(default_factory=list)
    replace_keys: list[str] = Field(default_factory=list)
    mode: Literal["replace", "append"] = "replace"


class PopulationGenerateResponse(BaseModel):
    generation_id: str
    fingerprint: list[list[int]]
    candidates: list[GenerationCandidate]


class PopulationSummary(BaseModel):
    id: int
    name: str
    size: int
    runs: int
    updated: str
    versions: int
    fp: list[list[int]]


class PopulationDetail(PopulationSummary):
    recipe: dict[str, Any] = Field(default_factory=dict)
    members: list[PopulationMemberOut] = Field(default_factory=list)


class PopulationCreate(BaseModel):
    name: str
    fingerprint: list[list[int]] = Field(default_factory=list)
    recipe: dict[str, Any] = Field(default_factory=dict)
    members: list[PopulationMemberCreate] = Field(default_factory=list)
    generation_id: str | None = None
    keep_keys: list[str] | None = None


class PopulationUpdate(BaseModel):
    name: str | None = None
    fingerprint: list[list[int]] | None = None
    recipe: dict[str, Any] | None = None
    members: list[PopulationMemberCreate] | None = None
    bump_version: bool = False
    generation_id: str | None = None
    keep_keys: list[str] | None = None


class PersonaGenerateRequest(BaseModel):
    mode: Literal["beskrivning", "demografi"] = "beskrivning"
    freeText: str = ""
    demografi: dict[str, str] = Field(default_factory=dict)
    count: int = Field(default=3, ge=1, le=8)


class PersonaGenerateResponse(BaseModel):
    candidates: list[EditablePersona]


ChatMode = Literal["interview", "character"]
ChatRole = Literal["user", "assistant"]


class PersonaChatRequest(BaseModel):
    mode: ChatMode = "interview"
    message: str = Field(min_length=1)


class PersonaMessageOut(BaseModel):
    id: int
    mode: ChatMode
    role: ChatRole
    content: str
    created_at: str


class PersonaChatResponse(BaseModel):
    reply: str
    messages: list[PersonaMessageOut]


RunStatus = Literal["done", "running", "draft", "failed"]
InjectionType = Literal["party_post", "news_post", "ad_post"]
InjectionMode = Literal["text", "link"]


class Injection(BaseModel):
    key: str
    type: InjectionType
    sender: str = ""
    text: str = ""
    mode: InjectionMode = "text"
    url: str = ""
    fetching: bool = False
    sourceDomain: str = ""
    isVideo: bool = False


class Tick(BaseModel):
    key: str
    day: int
    silent: bool = False
    injections: list[Injection] = Field(default_factory=list)
    rounds: int = 1
    measurements: list[str] = Field(default_factory=list)


class BranchState(BaseModel):
    afterIndex: int
    a: list[Tick] = Field(default_factory=list)
    b: list[Tick] = Field(default_factory=list)


class RunSummary(BaseModel):
    id: int
    name: str
    status: RunStatus
    population: str
    ticks: int
    variants: int
    seed: str
    updated: str


class RunDetail(RunSummary):
    population_id: int
    start_date: str | None = None
    main_ticks: list[Tick] = Field(default_factory=list)
    branch: BranchState | None = None
    results: dict[str, Any] | None = None


class RunCreate(BaseModel):
    name: str
    population_id: int
    seed: str = ""
    start_date: str | None = None
    status: RunStatus = "draft"
    main_ticks: list[Tick] = Field(default_factory=list)
    branch: BranchState | None = None


class RunUpdate(BaseModel):
    name: str | None = None
    population_id: int | None = None
    seed: str | None = None
    start_date: str | None = None
    status: RunStatus | None = None
    main_ticks: list[Tick] | None = None
    branch: BranchState | None = None


class RunPopulationOption(BaseModel):
    id: int
    name: str
    size: int
    initials: list[str]


def format_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.date().isoformat()
