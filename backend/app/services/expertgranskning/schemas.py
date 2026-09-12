"""Request/response models for the expertgranskning module API."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.domain import ConfigurationLanguage
from app.services.panel.schemas import PanelSessionStatus
from app.services.word.schemas import WordActionOut
from app.services.word.tasks import WordTask, validate_word_task_against_sections

WORD_MAX_SECTIONS = 200
WORD_MAX_PARAGRAPHS_PER_SECTION = 200
WORD_MAX_PARAGRAPHS = 400
WORD_MAX_HEADING_LEN = 4_000
WORD_MAX_STYLE_LEN = 128
WORD_MAX_PARAGRAPH_LEN = 20_000
WORD_MAX_DOCUMENT_CHARS = 200_000

INTENT_MAX_QUESTIONS = 5
INTENT_MAX_OPTIONS = 8
INTENT_MAX_DOCUMENT_TYPE_LEN = 200
INTENT_MAX_QUESTION_LEN = 500
INTENT_MAX_RATIONALE_LEN = 800
INTENT_MAX_OPTION_LABEL_LEN = 200
INTENT_MAX_FREE_TEXT_LEN = 2_000
INTENT_QUESTION_TYPES = ("single_choice", "multi_choice", "free_text")
IntentQuestionType = Literal["single_choice", "multi_choice", "free_text"]
INTENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SWEDISH_FOLDS = str.maketrans(
    {
        "å": "a",
        "ä": "a",
        "ö": "o",
        "Å": "a",
        "Ä": "a",
        "Ö": "o",
    }
)


def slugify_intent_id(value: object) -> str:
    text = "" if value is None else str(value).strip()
    folded = text.translate(_SWEDISH_FOLDS).casefold()
    chars: list[str] = []
    for char in folded:
        if "a" <= char <= "z" or "0" <= char <= "9":
            chars.append(char)
        else:
            chars.append("_")
    slug = "".join(chars)
    while "__" in slug:
        slug = slug.replace("__", "_")
    slug = slug.strip("_")[:64].rstrip("_")
    if not INTENT_ID_RE.fullmatch(slug):
        return ""
    return slug


class ExpertgranskningSessionCreate(BaseModel):
    """Create a session. Empty document/panel is allowed for drafts."""

    document_text: str = Field(default="", max_length=200_000)
    underlag_id: str | None = None
    panel_id: int | None = None
    title: str = ""
    review_intent: str = Field(default="", max_length=8_000)
    project_id: int | None = None

    @field_validator("document_text", "title", "review_intent", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("underlag_id", mode="before")
    @classmethod
    def empty_underlag_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class ExpertgranskningSessionUpdate(BaseModel):
    document_text: str | None = Field(default=None, max_length=200_000)
    underlag_id: str | None = None
    clear_underlag: bool = False
    panel_id: int | None = None
    title: str | None = None
    review_intent: str | None = Field(default=None, max_length=8_000)
    project_id: int | None = None
    clear_panel: bool = False

    @field_validator("document_text", "title", "review_intent", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return str(value).strip()

    @field_validator("underlag_id", mode="before")
    @classmethod
    def empty_underlag_id(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class ExpertgranskningSessionOut(BaseModel):
    id: str
    protocol: str
    status: PanelSessionStatus
    module: str
    topic: str
    document_text: str
    underlag_id: str | None = None
    review_intent: str = ""
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


def _require_intent_id(value: object, *, label: str) -> str:
    text = "" if value is None else str(value).strip()
    if not INTENT_ID_RE.fullmatch(text):
        raise ValueError(f"{label} must be a machine-readable slug")
    return text


class IntentOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(max_length=64)
    label: str = Field(max_length=INTENT_MAX_OPTION_LABEL_LEN)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: object) -> str:
        return _require_intent_id(value, label="option value")

    @field_validator("label", mode="before")
    @classmethod
    def strip_label(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        if not value:
            raise ValueError("option label is required")
        return value


class IntentQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    text: str = Field(max_length=INTENT_MAX_QUESTION_LEN)
    type: IntentQuestionType
    options: list[IntentOption] = Field(default_factory=list, max_length=INTENT_MAX_OPTIONS)
    required: bool = True
    rationale: str = Field(max_length=INTENT_MAX_RATIONALE_LEN)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: object) -> str:
        return _require_intent_id(value, label="question id")

    @field_validator("text", "rationale", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("text")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value:
            raise ValueError("question text is required")
        return value

    @field_validator("rationale")
    @classmethod
    def require_rationale(cls, value: str) -> str:
        if not value:
            raise ValueError("question rationale is required")
        return value

    @model_validator(mode="after")
    def validate_options_for_type(self) -> IntentQuestion:
        values = [option.value for option in self.options]
        if len(values) != len(set(values)):
            raise ValueError("option values must be unique")
        if self.type == "free_text":
            if self.options:
                raise ValueError("free_text questions cannot have options")
            return self
        if self.type in {"single_choice", "multi_choice"}:
            if len(self.options) < 2:
                raise ValueError("choice questions need at least two options")
            return self
        raise ValueError(f"unknown question type: {self.type}")


class DocumentIntentInterview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(max_length=INTENT_MAX_DOCUMENT_TYPE_LEN)
    questions: list[IntentQuestion] = Field(
        default_factory=list,
        max_length=INTENT_MAX_QUESTIONS,
    )

    @field_validator("document_type", mode="before")
    @classmethod
    def strip_document_type(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("document_type")
    @classmethod
    def require_document_type(cls, value: str) -> str:
        if not value:
            raise ValueError("document_type is required")
        return value

    @model_validator(mode="after")
    def unique_question_ids(self) -> DocumentIntentInterview:
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return self


class IntentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(max_length=64)
    selected_values: list[str] = Field(default_factory=list, max_length=INTENT_MAX_OPTIONS)
    free_text: str | None = Field(default=None, max_length=INTENT_MAX_FREE_TEXT_LEN)

    @field_validator("question_id")
    @classmethod
    def validate_question_id(cls, value: object) -> str:
        return _require_intent_id(value, label="question_id")

    @field_validator("selected_values", mode="before")
    @classmethod
    def strip_selected_values(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("free_text", mode="before")
    @classmethod
    def empty_free_text(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


def validate_intent_answers(
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
) -> None:
    if interview is None:
        if answers:
            raise ValueError("intent_answers require intent_interview")
        return
    by_id = {question.id: question for question in interview.questions}
    seen: set[str] = set()
    for answer in answers:
        if answer.question_id in seen:
            raise ValueError(f"duplicate answer for {answer.question_id}")
        seen.add(answer.question_id)
        question = by_id.get(answer.question_id)
        if question is None:
            raise ValueError(f"unknown question_id: {answer.question_id}")
        _validate_one_intent_answer(question, answer)
    missing = [
        question.id
        for question in interview.questions
        if question.required and question.id not in seen
    ]
    if missing:
        raise ValueError(f"missing answers for required questions: {', '.join(missing)}")


def _validate_one_intent_answer(question: IntentQuestion, answer: IntentAnswer) -> None:
    allowed = {option.value for option in question.options}
    if question.type == "single_choice":
        if answer.free_text is not None:
            raise ValueError(f"{question.id} cannot include free_text")
        if len(answer.selected_values) != 1:
            raise ValueError(f"{question.id} requires exactly one selected value")
        if answer.selected_values[0] not in allowed:
            raise ValueError(f"{question.id} selected an unknown option")
        return
    if question.type == "multi_choice":
        if answer.free_text is not None:
            raise ValueError(f"{question.id} cannot include free_text")
        if not answer.selected_values:
            raise ValueError(f"{question.id} requires at least one selected value")
        if len(answer.selected_values) != len(set(answer.selected_values)):
            raise ValueError(f"{question.id} selected values must be unique")
        unknown = [value for value in answer.selected_values if value not in allowed]
        if unknown:
            raise ValueError(f"{question.id} selected unknown options")
        return
    if question.type == "free_text":
        if answer.selected_values:
            raise ValueError(f"{question.id} cannot include selected_values")
        if question.required and not (answer.free_text or "").strip():
            raise ValueError(f"{question.id} requires free_text")
        return
    raise ValueError(f"unknown question type: {question.type}")


class ExpertgranskningIntentInterviewCreate(BaseModel):
    panel_id: int
    sections: list[WordDocumentSection] = Field(min_length=1, max_length=WORD_MAX_SECTIONS)
    locale: ConfigurationLanguage = "sv"

    @model_validator(mode="after")
    def bound_document(self) -> ExpertgranskningIntentInterviewCreate:
        _bound_word_sections(self.sections)
        return self


class ExpertgranskningWordJobCreate(BaseModel):
    task: WordTask
    doc_id: str | None = Field(default=None, max_length=128)
    word_session_id: str | None = Field(default=None, max_length=64)
    review_intent: str = Field(default="", max_length=8_000)
    intent_interview: DocumentIntentInterview | None = None
    intent_answers: list[IntentAnswer] = Field(default_factory=list)
    sections: list[WordDocumentSection] = Field(min_length=1, max_length=WORD_MAX_SECTIONS)
    locale: ConfigurationLanguage = "sv"

    @field_validator("review_intent", mode="before")
    @classmethod
    def strip_review_intent(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("doc_id", "word_session_id", mode="before")
    @classmethod
    def empty_doc_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @model_validator(mode="after")
    def bound_document_and_task(self) -> ExpertgranskningWordJobCreate:
        _bound_word_sections(self.sections)
        validate_word_task_against_sections(self.task, self.sections)
        validate_intent_answers(self.intent_interview, self.intent_answers)
        return self


class ExpertgranskningWordJobRequest(BaseModel):
    """Payload stored on an expertgranskning_word_review job."""

    customer_id: int
    owner_user_id: str
    doc_id: str | None = Field(default=None, max_length=128)
    word_session_id: str | None = Field(default=None, max_length=64)
    review_intent: str = Field(default="", max_length=8_000)
    intent_interview: DocumentIntentInterview | None = None
    intent_answers: list[IntentAnswer] = Field(default_factory=list)
    locale: ConfigurationLanguage = "sv"
    task: WordTask
    sections: list[WordDocumentSection] = Field(min_length=1, max_length=WORD_MAX_SECTIONS)

    @field_validator("word_session_id", mode="before")
    @classmethod
    def empty_session_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("review_intent", mode="before")
    @classmethod
    def strip_review_intent(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @model_validator(mode="after")
    def bound_document_and_task(self) -> ExpertgranskningWordJobRequest:
        _bound_word_sections(self.sections)
        validate_word_task_against_sections(self.task, self.sections)
        validate_intent_answers(self.intent_interview, self.intent_answers)
        return self

    @property
    def panel_id(self) -> int:
        return self.task.expert_strategy.panel_id


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
    primary_anchor_paragraph_index: int | None = None
    recommended_expert_ids: list[str] = Field(default_factory=list)

    @field_validator("id", "question", "why_it_matters", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("primary_anchor_paragraph_index", mode="before")
    @classmethod
    def empty_primary_is_omitted(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("recommended_expert_ids", mode="before")
    @classmethod
    def strip_recommended_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(item).strip() for item in value if str(item).strip()]


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


WordIssueMateriality = Literal["high", "medium", "low"]
WordIssueActionability = Literal["actionable", "informational"]
WordIssueNovelty = Literal["new", "overlap"]
_WORD_ISSUE_MATERIALITY = frozenset({"high", "medium", "low"})
_WORD_ISSUE_ACTIONABILITY = frozenset({"actionable", "informational"})
_WORD_ISSUE_NOVELTY = frozenset({"new", "overlap"})


def _optional_issue_literal(value: object, allowed: frozenset[str]) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text not in allowed:
        return None
    return text


class WordLlmConvergedIssue(BaseModel):
    """LLM-facing issue. Classification fields may be omitted or invalid."""

    observation_ids: list[str] = Field(default_factory=list)
    paragraph_index: int
    supporting_expert_ids: list[str] = Field(default_factory=list)
    short_comment: str
    explanation: str
    materiality: WordIssueMateriality | None = None
    actionability: WordIssueActionability | None = None
    novelty: WordIssueNovelty | None = None
    should_materialize: bool | None = None
    has_dissensus: bool = False

    @field_validator("short_comment", "explanation", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("observation_ids", "supporting_expert_ids", mode="before")
    @classmethod
    def strip_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("materiality", mode="before")
    @classmethod
    def optional_materiality(cls, value: object) -> str | None:
        return _optional_issue_literal(value, _WORD_ISSUE_MATERIALITY)

    @field_validator("actionability", mode="before")
    @classmethod
    def optional_actionability(cls, value: object) -> str | None:
        return _optional_issue_literal(value, _WORD_ISSUE_ACTIONABILITY)

    @field_validator("novelty", mode="before")
    @classmethod
    def optional_novelty(cls, value: object) -> str | None:
        return _optional_issue_literal(value, _WORD_ISSUE_NOVELTY)

    @field_validator("should_materialize", mode="before")
    @classmethod
    def optional_should_materialize(cls, value: object) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        return None


class WordConvergedIssue(WordLlmConvergedIssue):
    """Finalized Word-review issue. Classification fields are required."""

    materiality: WordIssueMateriality
    actionability: WordIssueActionability
    novelty: WordIssueNovelty
    should_materialize: bool


class WordCommentConvergence(BaseModel):
    issues: list[WordLlmConvergedIssue] = Field(default_factory=list)


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
    created_at: str


class ExpertgranskningLatestWordJobOut(BaseModel):
    job_id: str
    status: str
    error: str | None = None
    actions: list[WordActionOut]
