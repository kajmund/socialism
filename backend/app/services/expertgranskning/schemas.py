"""Request/response models for the expertgranskning module API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.panel.schemas import PanelSessionStatus


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
    text: str
    style: str = ""

    @field_validator("text", "style", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)


class WordDocumentSection(BaseModel):
    heading: str = ""
    heading_style: str = ""
    heading_paragraph_index: int
    paragraphs: list[WordDocumentParagraph] = Field(default_factory=list)

    @field_validator("heading", "heading_style", mode="before")
    @classmethod
    def strip_heading(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)


class ExpertgranskningWordJobCreate(BaseModel):
    panel_id: int
    doc_id: str | None = None
    sections: list[WordDocumentSection] = Field(min_length=1)
    locale: str = "sv"

    @field_validator("doc_id", mode="before")
    @classmethod
    def empty_doc_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class ExpertgranskningWordJobRequest(BaseModel):
    """Payload stored on an expertgranskning_word_review job."""

    panel_id: int
    customer_id: int
    owner_user_id: str
    doc_id: str | None = None
    sections: list[WordDocumentSection]
    locale: str = "sv"


class WordParagraphComment(BaseModel):
    expert_id: str
    expert_namn: str
    kommentar: str


class WordParagraphComments(BaseModel):
    comments: list[WordParagraphComment] = Field(default_factory=list)


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
    comment_id: str | None
    status: str
    created_at: str
