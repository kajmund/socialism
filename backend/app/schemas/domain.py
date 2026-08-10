from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

PersonaOrigin = Literal["manuell", "beskrivning", "demografi", "population"]


class EditablePersona(BaseModel):
    name: str
    initials: str = "--"
    age: str = "—"
    kön: str = "—"
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
    # Genereras vid persona-skapande — inte ett recept-/katalogfält.
    anekdot: str = "—"


class PersonaAnecdoteOut(BaseModel):
    # ~20 Swedish words ≈ 120–140 chars; keep a hard char cap in the JSON schema
    # so the model sees a bound (word-count is enforced in the validator).
    anekdot: str = Field(
        min_length=8,
        max_length=140,
        description="One short Swedish everyday sentence, at most 20 words.",
    )

    @field_validator("anekdot")
    @classmethod
    def normalize_anecdote(cls, value: str) -> str:
        text = " ".join(value.split())
        if not text:
            raise ValueError("anekdot is empty")
        words = text.split()
        if len(words) > 20:
            raise ValueError("anekdot exceeds 20 words")
        return text


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
    profile: EditablePersona


class PersonaDetail(LibraryPersona):
    pass


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
    dist: dict[str, DistGroup]
    locale: str = "local"
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
    warnings: list[str] = Field(default_factory=list)


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
    run_id: int | None = None
    attempt_id: str | None = None
    variant_id: str | None = None
    through_tick_index: int | None = None


class PersonaChatResponse(BaseModel):
    reply: str
    messages: list[PersonaMessageOut]


class PersonaMessageDeleteResponse(BaseModel):
    deleted_ids: list[int]


class RunPersonaInterviewRequest(BaseModel):
    through_tick_index: int = Field(ge=0)
    message: str = Field(min_length=1)


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
    message_id: str | None = None


MessageType = Literal["post", "news"]
MessageVariant = Literal["analytical", "narrative", "concise"]


class MessageOut(BaseModel):
    id: str
    type: MessageType
    title: str
    body: str
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    image_sha256: str | None = None
    image_caption: str | None = None
    created_at: str


def _message_image_sha256(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    raw = metadata.get("image_sha256")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return None


def _strip_optional_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    return value.strip()


def _strip_required_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty or whitespace-only")
    return stripped


class MessageCreate(BaseModel):
    id: str | None = None
    type: MessageType
    title: str = Field(min_length=1, max_length=255)
    body: str = ""
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        return _strip_required_text(value)

    @field_validator("body", mode="before")
    @classmethod
    def strip_body(cls, value: object) -> object:
        return _strip_optional_text(value)

    @model_validator(mode="after")
    def require_content(self) -> "MessageCreate":
        body_ok = bool(self.body.strip())
        digest = _message_image_sha256(self.metadata)
        if not body_ok and not digest:
            raise ValueError("body or metadata.image_sha256 is required")
        return self

class MessageUpdate(BaseModel):
    type: MessageType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        if value is None:
            return None
        return _strip_required_text(value)

    @field_validator("body", mode="before")
    @classmethod
    def strip_body(cls, value: object) -> object:
        if value is None:
            return None
        return _strip_optional_text(value)


class SummarizeUrlRequest(BaseModel):
    url: str = Field(min_length=1)
    message_type: MessageType = "news"


class SummarizeUrlResponse(BaseModel):
    summary: str
    source_url: str
    source_domain: str = ""


class GenerateVariantsRequest(BaseModel):
    type: MessageType
    raw_text: str = ""
    source_url: str | None = None
    audience: str = ""
    purpose: str = ""
    tone: str = ""

    @field_validator("raw_text")
    @classmethod
    def strip_raw(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_input(self) -> "GenerateVariantsRequest":
        if not self.raw_text and not (self.source_url or "").strip():
            raise ValueError("raw_text or source_url is required")
        return self

class MessageVariantOut(BaseModel):
    key: MessageVariant
    label: str
    body: str


class GenerateVariantsResponse(BaseModel):
    variants: list[MessageVariantOut]


def new_message_id() -> str:
    return str(uuid4())


ConfigurationLanguage = Literal["sv", "en", "nb"]


# Default matches playground calibration default (sharper than Softmax T=1.0).
DEFAULT_SSR_TEMPERATURE = 0.1

AnchorKind = Literal["tone", "style"]
AnchorLocale = Literal["sv", "en"]
AnchorStatus = Literal["draft", "published"]


class ConfigurationAnchorRef(BaseModel):
    tone: int = Field(gt=0)
    style: int = Field(gt=0)


class ConfigurationAnchorSets(BaseModel):
    sv: ConfigurationAnchorRef
    en: ConfigurationAnchorRef


class ConfigurationOut(BaseModel):
    id: int
    name: str
    language: ConfigurationLanguage
    prompts: dict[str, str]
    ssr_temperature: float
    anchor_sets: ConfigurationAnchorSets
    is_active: bool
    created_at: str
    updated_at: str


class ConfigurationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    language: ConfigurationLanguage
    prompts: dict[str, str] = Field(default_factory=dict)
    ssr_temperature: float = Field(default=DEFAULT_SSR_TEMPERATURE, gt=0, le=10)
    anchor_sets: ConfigurationAnchorSets | None = None
    is_active: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return _strip_required_text(value)


class ConfigurationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    language: ConfigurationLanguage | None = None
    prompts: dict[str, str] | None = None
    ssr_temperature: float | None = Field(default=None, gt=0, le=10)
    anchor_sets: ConfigurationAnchorSets | None = None
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if value is None:
            return None
        return _strip_required_text(value)


class PromptFieldOut(BaseModel):
    key: str
    section: str
    label: str
    hint: str
    default: str


class SsrAnchorSetOut(BaseModel):
    id: int
    name: str
    kind: AnchorKind
    locale: AnchorLocale
    version: str
    labels: list[str]
    statements: list[str]
    status: AnchorStatus
    created_at: str
    updated_at: str


class SsrAnchorSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: AnchorKind
    locale: AnchorLocale
    version: str = Field(default="v1", min_length=1, max_length=16)
    labels: list[str] = Field(min_length=1)
    statements: list[str] = Field(min_length=1)
    status: AnchorStatus = "draft"

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return _strip_required_text(value)


class SsrAnchorSetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, min_length=1, max_length=16)
    labels: list[str] | None = None
    statements: list[str] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if value is None:
            return None
        return _strip_required_text(value)


class SsrAnchorCalibrationItemOut(BaseModel):
    id: int
    text: str
    human_label: str
    sort_order: int
    created_at: str


class SsrAnchorCalibrationItemCreate(BaseModel):
    text: str = Field(min_length=1)
    human_label: str = Field(min_length=1, max_length=64)
    sort_order: int = 0

    @field_validator("text", "human_label", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return _strip_required_text(value)


class SsrAnchorCalibrationItemUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    human_label: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: int | None = None

    @field_validator("text", "human_label", mode="before")
    @classmethod
    def strip_optional(cls, value: object) -> object:
        if value is None:
            return None
        return _strip_required_text(value)


class SsrAnchorTestRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    temperature: float = Field(default=DEFAULT_SSR_TEMPERATURE, gt=0, le=10)
    use_calibration: bool = False


class PromptCatalogOut(BaseModel):
    sections: list[dict[str, str]]
    fields: list[PromptFieldOut]
    defaults: dict[str, str]


class TickInterview(BaseModel):
    """Planned OASIS INTERVIEW after a tick's reaction rounds."""

    key: str = ""
    persona_id: str
    prompt: str = Field(min_length=1)


class Tick(BaseModel):
    key: str
    day: int
    silent: bool = False
    injections: list[Injection] = Field(default_factory=list)
    rounds: int = 3
    measurements: list[str] = Field(default_factory=list)
    interviews: list[TickInterview] = Field(default_factory=list)


BranchMode = Literal["ab", "stimulus_control"]


class BranchState(BaseModel):
    afterIndex: int
    a: list[Tick] = Field(default_factory=list)
    b: list[Tick] = Field(default_factory=list)
    mode: BranchMode = "ab"


OasisPlatform = Literal["twitter", "reddit"]


class OasisRunOptions(BaseModel):
    """Per-run OASIS simulation knobs."""

    platform: OasisPlatform = "twitter"
    allow_population_create_post: bool = True
    enable_search_duckduckgo: bool = False
    enable_search_wiki: bool = False
    enable_sympy_tools: bool = False

    @model_validator(mode="before")
    @classmethod
    def expand_legacy_web_search(cls, data: Any) -> Any:
        """Map deprecated enable_web_search → both search flags when unset."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        legacy = out.pop("enable_web_search", None)
        if legacy is None:
            return out
        enabled = bool(legacy)
        if "enable_search_duckduckgo" not in out:
            out["enable_search_duckduckgo"] = enabled
        if "enable_search_wiki" not in out:
            out["enable_search_wiki"] = enabled
        return out


class RunSummary(BaseModel):
    id: int
    name: str
    status: RunStatus
    population: str
    ticks: int
    variants: int
    seed: str = ""
    updated: str


class RunDetail(RunSummary):
    population_id: int
    start_date: str | None = None
    main_ticks: list[Tick] = Field(default_factory=list)
    branch: BranchState | None = None
    oasis_options: OasisRunOptions = Field(default_factory=OasisRunOptions)
    results: dict[str, Any] | None = None
    job_id: str | None = None


class RunCreate(BaseModel):
    name: str
    population_id: int
    start_date: str | None = None
    status: RunStatus = "draft"
    main_ticks: list[Tick] = Field(default_factory=list)
    branch: BranchState | None = None
    oasis_options: OasisRunOptions = Field(default_factory=OasisRunOptions)


class RunUpdate(BaseModel):
    name: str | None = None
    population_id: int | None = None
    start_date: str | None = None
    status: RunStatus | None = None
    main_ticks: list[Tick] | None = None
    branch: BranchState | None = None
    oasis_options: OasisRunOptions | None = None


class RunPopulationOption(BaseModel):
    id: int
    name: str
    size: int
    initials: list[str]


def format_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.date().isoformat()


CatalogSection = Literal["demografi", "politik", "varderingar", "rost_media", "simulering"]


class GeoBounds(BaseModel):
    """Axis-aligned WGS84 rectangle (south/west/north/east)."""

    south: float
    west: float
    north: float
    east: float

    @model_validator(mode="after")
    def validate_rect(self) -> "GeoBounds":
        if self.south >= self.north:
            raise ValueError("south must be less than north")
        if self.west >= self.east:
            raise ValueError("west must be less than east")
        return self


class CatalogItem(BaseModel):
    label: str
    description: str = ""
    bounds: GeoBounds | None = None


class CatalogListOut(BaseModel):
    key: str
    section: CatalogSection
    title: str
    items: list[CatalogItem]
    updated_at: str


class CatalogListUpdate(BaseModel):
    items: list[CatalogItem]

    @field_validator("items", mode="before")
    @classmethod
    def coerce_items(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return value
        out: list[Any] = []
        for raw in value:
            if isinstance(raw, str):
                out.append({"label": raw, "description": "", "bounds": None})
            else:
                out.append(raw)
        return out

    @field_validator("items")
    @classmethod
    def clean_items(cls, value: list[CatalogItem]) -> list[CatalogItem]:
        cleaned: list[CatalogItem] = []
        seen: set[str] = set()
        for item in value:
            label = item.label.strip()
            if not label or label in seen:
                continue
            seen.add(label)
            cleaned.append(
                CatalogItem(
                    label=label,
                    description=item.description.strip(),
                    bounds=item.bounds,
                )
            )
        return cleaned


JobKind = Literal["population_generate", "run_simulate", "report_generate"]
JobStatus = Literal["pending", "running", "succeeded", "failed"]
ReportStatus = Literal["pending", "running", "succeeded", "failed"]


class PopulationGenerateJobRequest(BaseModel):
    """Payload stored on a population_generate job."""

    name: str
    recipe: PopulationRecipe
    population_id: int | None = None
    include_persona_ids: list[str] = Field(default_factory=list)


class RunSimulateJobRequest(BaseModel):
    """Payload stored on a run_simulate job."""

    run_id: int


class ReportSource(BaseModel):
    run_id: int
    attempt_id: str


class ReportGenerateJobRequest(BaseModel):
    """Payload stored on a report_generate job."""

    report_id: str


class ReportCreate(BaseModel):
    sources: list[ReportSource] = Field(min_length=1)
    title: str = ""
    locale: Literal["sv", "en"] = "sv"
    mode: Literal["full", "quick"] = "full"


class ReportOut(BaseModel):
    id: str
    status: ReportStatus
    title: str
    locale: Literal["sv", "en"] = "sv"
    mode: Literal["full", "quick"] = "full"
    sources: list[ReportSource]
    html_path: str | None = None
    slots_path: str | None = None
    job_id: str | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None
    updated_at: str


class JobCreate(BaseModel):
    kind: JobKind
    label: str = ""
    request: dict[str, Any] = Field(default_factory=dict)


class JobOut(BaseModel):
    id: str
    kind: str
    status: JobStatus
    label: str
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str
