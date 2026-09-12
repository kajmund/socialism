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


def _optional_local_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class WordDocumentParagraph(BaseModel):
    """Raw Word paragraph. Server owns the skip filter."""

    index: int
    text: str = Field(max_length=WORD_MAX_PARAGRAPH_LEN)
    style: str = Field(default="", max_length=WORD_MAX_STYLE_LEN)
    list_string: str = Field(default="", max_length=64)
    unique_local_id: str | None = Field(default=None, max_length=64)

    @field_validator("text", "style", "list_string", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("unique_local_id", mode="before")
    @classmethod
    def empty_local_id(cls, value: object) -> str | None:
        return _optional_local_id(value)


class WordDocumentSection(BaseModel):
    heading: str = Field(default="", max_length=WORD_MAX_HEADING_LEN)
    heading_style: str = Field(default="", max_length=WORD_MAX_STYLE_LEN)
    heading_paragraph_index: int
    heading_unique_local_id: str | None = Field(default=None, max_length=64)
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

    @field_validator("heading_unique_local_id", mode="before")
    @classmethod
    def empty_heading_local_id(cls, value: object) -> str | None:
        return _optional_local_id(value)


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
    word_session_id: str | None = Field(default=None, max_length=64)
    sections: list[WordDocumentSection] = Field(min_length=1, max_length=WORD_MAX_SECTIONS)
    locale: ConfigurationLanguage = "sv"

    @field_validator("doc_id", "word_session_id", mode="before")
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
    word_session_id: str | None = Field(default=None, max_length=64)
    sections: list[WordDocumentSection] = Field(min_length=1, max_length=WORD_MAX_SECTIONS)
    locale: ConfigurationLanguage = "sv"

    @field_validator("word_session_id", mode="before")
    @classmethod
    def empty_session_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

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

    @field_validator("ny_text", "motivering", mode="before")
    @classmethod
    def none_to_empty(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("ny_text")
    @classmethod
    def single_paragraph(cls, value: str) -> str:
        if "\n" in value.replace("\r\n", "\n").replace("\r", "\n"):
            return ""
        return value


class WordReviewQuestion(BaseModel):
    id: str
    paragraph_indexes: list[int] = Field(default_factory=list)
    question: str
    why_it_matters: str = ""

    @field_validator("id", "question", "why_it_matters", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class WordBatchModeration(BaseModel):
    needs_review: bool
    reason: str = ""
    questions: list[WordReviewQuestion] = Field(default_factory=list)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class WordExpertRaiseHand(BaseModel):
    question_ids: list[str] = Field(default_factory=list)

    @field_validator("question_ids", mode="before")
    @classmethod
    def strip_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(item).strip() for item in value if str(item).strip()]


class WordExpertComment(BaseModel):
    kommentar: str = ""
    anchor_paragraph_index: int | None = None

    @field_validator("anchor_paragraph_index", mode="before")
    @classmethod
    def empty_anchor_is_omitted(cls, value: object) -> object:
        if value == "":
            return None
        return value


class WordConvergedIssue(BaseModel):
    """One Word comment after observation-level consolidation."""

    observation_ids: list[str] = Field(default_factory=list)
    paragraph_index: int
    supporting_expert_ids: list[str] = Field(default_factory=list)
    kommentar: str = ""
    has_dissensus: bool = False

    @field_validator("kommentar", mode="before")
    @classmethod
    def strip_comment(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("observation_ids", "supporting_expert_ids", mode="before")
    @classmethod
    def strip_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(item).strip() for item in value if str(item).strip()]


class WordCommentConvergence(BaseModel):
    issues: list[WordConvergedIssue] = Field(default_factory=list)


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


class WordAnchorOut(BaseModel):
    paragraph_index: int
    unique_local_id: str | None = None
    reviewed_text: str
    text_hash: str
    previous_text_hash: str | None = None
    next_text_hash: str | None = None
    word_session_id: str | None = None


class WordApplicationClaimIn(BaseModel):
    application_id: str = Field(min_length=1, max_length=64)


class WordApplicationCompleteIn(BaseModel):
    application_id: str = Field(min_length=1, max_length=64)
    comment_id: str | None = Field(default=None, max_length=128)

    @field_validator("comment_id", mode="before")
    @classmethod
    def empty_comment_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class WordApplicationUnresolvedIn(BaseModel):
    application_id: str | None = Field(default=None, max_length=64)
    reason: str = Field(min_length=1, max_length=64)

    @field_validator("application_id", mode="before")
    @classmethod
    def empty_application_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


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
    anchor: WordAnchorOut | None = None
    comment_id: str | None
    application_id: str | None = None
    application_error: str | None = None
    status: str
    created_at: str


class ExpertgranskningLatestWordJobOut(BaseModel):
    job_id: str
    status: str
    results: list[ExpertgranskningResultOut]
