"""Request/response models for the expertgranskning module API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.domain import ConfigurationLanguage
from app.services.panel.schemas import PanelSessionStatus

WORD_MAX_SECTIONS = 200
WORD_MAX_PARAGRAPHS_PER_SECTION = 200
WORD_MAX_PARAGRAPHS = 400
WORD_MAX_HEADING_LEN = 4_000
WORD_MAX_STYLE_LEN = 128
WORD_MAX_PARAGRAPH_LEN = 20_000
WORD_MAX_DOCUMENT_CHARS = 200_000


class ExpertgranskningSessionCreate(BaseModel):
    """Create a session. Empty document/panel is allowed for drafts."""

    document_text: str = Field(default="", max_length=200_000)
    panel_id: int | None = None
    title: str = ""
    project_id: int | None = None

    @field_validator("document_text", "title", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class ExpertgranskningSessionUpdate(BaseModel):
    document_text: str | None = Field(default=None, max_length=200_000)
    panel_id: int | None = None
    title: str | None = None
    project_id: int | None = None
    clear_panel: bool = False

    @field_validator("document_text", "title", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return str(value).strip()


class ExpertgranskningSessionOut(BaseModel):
    id: str
    protocol: str
    status: PanelSessionStatus
    module: str
    topic: str
    document_text: str
    panel_id: int | None
    panel_name: str | None = None
    project_id: int | None
    job_id: str | None
    error: str | None
    created_at: str
    updated_at: str


class ExpertgranskningSessionSummary(BaseModel):
    id: str
    topic: str
    status: PanelSessionStatus
    panel_id: int | None
    panel_name: str | None
    job_id: str | None
    created_at: str
    updated_at: str


class WordDocumentParagraph(BaseModel):
    """Raw Word paragraph. Server owns the skip filter."""

    index: int
    text: str = Field(max_length=WORD_MAX_PARAGRAPH_LEN)
    style: str = Field(default="", max_length=WORD_MAX_STYLE_LEN)

    @field_validator("text", "style", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)


class WordDocumentSection(BaseModel):
    heading: str = Field(default="", max_length=WORD_MAX_HEADING_LEN)
    heading_style: str = Field(default="", max_length=WORD_MAX_STYLE_LEN)
    heading_paragraph_index: int
    paragraphs: list[WordDocumentParagraph] = Field(
        default_factory=list,
        max_length=WORD_MAX_PARAGRAPHS_PER_SECTION,
    )

    @field_validator("heading", "heading_style", mode="before")
    @classmethod
    def strip_heading(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)


def _bound_word_sections(sections: list[WordDocumentSection]) -> None:
    total_paragraphs = sum(len(section.paragraphs) for section in sections)
    if total_paragraphs > WORD_MAX_PARAGRAPHS:
        raise ValueError(
            f"Document has {total_paragraphs} paragraphs; max is {WORD_MAX_PARAGRAPHS}"
        )
    total_chars = sum(
        len(section.heading) + sum(len(paragraph.text) for paragraph in section.paragraphs)
        for section in sections
    )
    if total_chars > WORD_MAX_DOCUMENT_CHARS:
        raise ValueError(
            f"Document has {total_chars} characters; max is {WORD_MAX_DOCUMENT_CHARS}"
        )


class ExpertgranskningWordJobCreate(BaseModel):
    panel_id: int
    doc_id: str | None = Field(default=None, max_length=128)
    sections: list[WordDocumentSection] = Field(min_length=1, max_length=WORD_MAX_SECTIONS)
    locale: ConfigurationLanguage = "sv"

    @field_validator("doc_id", mode="before")
    @classmethod
    def empty_doc_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @model_validator(mode="after")
    def bound_document(self) -> ExpertgranskningWordJobCreate:
        _bound_word_sections(self.sections)
        return self


class ExpertgranskningWordJobRequest(BaseModel):
    """Payload stored on an expertgranskning_word_review job."""

    panel_id: int
    customer_id: int
    owner_user_id: str
    doc_id: str | None = Field(default=None, max_length=128)
    sections: list[WordDocumentSection] = Field(min_length=1, max_length=WORD_MAX_SECTIONS)
    locale: ConfigurationLanguage = "sv"

    @model_validator(mode="after")
    def bound_document(self) -> ExpertgranskningWordJobRequest:
        _bound_word_sections(self.sections)
        return self


class WordParagraphComment(BaseModel):
    expert_id: str
    expert_namn: str
    kommentar: str


class WordRewriteSuggestion(BaseModel):
    ny_text: str = ""
    motivering: str = ""

    @field_validator("ny_text")
    @classmethod
    def single_paragraph(cls, value: object) -> str:
        text = "" if value is None else str(value)
        if "\n" in text.replace("\r\n", "\n").replace("\r", "\n"):
            return ""
        return text


class WordParagraphComments(BaseModel):
    comments: list[WordParagraphComment] = Field(default_factory=list)
    omskrivning_forslag: WordRewriteSuggestion | None = Field(
        default=None,
        description=(
            "Set only when expert comments converge on the same concrete wording "
            "fix. Null on disagreement, partial overlap, or a single wording "
            "opinion. Never invent a compromise rewrite."
        ),
    )


class WordHeadingAssessment(BaseModel):
    forslag: str | None = None

    @field_validator("forslag", mode="before")
    @classmethod
    def empty_forslag(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class ExpertgranskningResultPatch(BaseModel):
    comment_id: str = Field(min_length=1, max_length=128)


class ExpertgranskningResultOut(BaseModel):
    id: str
    job_id: str
    customer_id: int
    section_index: int
    paragraph_index: int
    expert_id: str
    expert_namn: str
    kommentar: str
    is_heading_suggestion: bool
    is_rewrite_suggestion: bool = False
    foreslagen_text: str | None = None
    reviewed_text: str | None = None
    comment_id: str | None
    status: str
    created_at: str


class ExpertgranskningLatestWordJobOut(BaseModel):
    job_id: str
    status: str
    results: list[ExpertgranskningResultOut]
