"""Generate and compose a generic document-driven intent interview."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.llm import ChatMessage
from app.services.expertgranskning.schemas import (
    INTENT_ID_RE,
    INTENT_MAX_QUESTIONS,
    DocumentIntentInterview,
    IntentAnswer,
    IntentQuestion,
    WordDocumentSection,
    is_custom_choice_answer,
    slugify_intent_id,
)
from app.services.expertgranskning.word_structured import complete_word_structured
from app.services.panel.review_intent import (
    compose_brief_with_review_intent,
    render_review_intent_message,
)
from app.services.prompt_catalog import render_prompt
from app.services.review_contract import messages_with_output_contract

DOCUMENT_DATA_OPEN = "<document>"
DOCUMENT_DATA_CLOSE = "</document>"


def _llm_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


class LlmIntentOption(BaseModel):
    """LLM-facing option. Nested so JSON Schema exposes value/label."""

    model_config = ConfigDict(extra="ignore")

    value: str = Field(default="", description="Machine-readable option value")
    label: str = Field(default="", description="Visible option label")

    @field_validator("value", "label", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        return _llm_text(value)


class LlmIntentQuestion(BaseModel):
    """LLM-facing question. Nested so JSON Schema exposes text/type/options."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="", description="Machine-readable question id")
    text: str = Field(default="", description="Question shown to the reviewer")
    question: str = Field(
        default="",
        description="Fallback question text when text is empty",
    )
    type: str = Field(
        default="",
        description="single_choice, multi_choice, or free_text",
    )
    options: list[LlmIntentOption] = Field(default_factory=list)
    required: bool = True
    rationale: str = Field(default="", description="Why this question matters")

    @field_validator("id", "text", "question", "type", "rationale", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        return _llm_text(value)

    @field_validator("options", mode="before")
    @classmethod
    def coerce_options(cls, value: object) -> object:
        if not isinstance(value, list):
            return []
        kept: list[LlmIntentOption] = []
        for item in value:
            if isinstance(item, LlmIntentOption):
                kept.append(item)
                continue
            if not isinstance(item, dict):
                continue
            try:
                kept.append(LlmIntentOption.model_validate(item))
            except ValidationError:
                continue
        return kept

    @field_validator("required", mode="before")
    @classmethod
    def coerce_required(cls, value: object) -> object:
        if value is None:
            return True
        return value


class LlmDocumentIntentInterview(BaseModel):
    """Lenient LLM envelope. Finalization drops bad questions, not the interview."""

    model_config = ConfigDict(extra="ignore")

    document_type: str = Field(
        default="",
        description="Short descriptive document-type label",
    )
    questions: list[LlmIntentQuestion] = Field(default_factory=list)

    @field_validator("document_type", mode="before")
    @classmethod
    def strip_document_type(cls, value: object) -> str:
        return _llm_text(value)

    @field_validator("questions", mode="before")
    @classmethod
    def coerce_questions(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        kept: list[LlmIntentQuestion] = []
        for item in value:
            if isinstance(item, LlmIntentQuestion):
                kept.append(item)
                continue
            if not isinstance(item, dict):
                continue
            try:
                kept.append(LlmIntentQuestion.model_validate(item))
            except ValidationError:
                continue
        return kept


def _unique_slug(base: str, seen: set[str]) -> str:
    if base not in seen:
        return base
    for suffix in range(2, 21):
        trimmed = base[: 64 - (len(str(suffix)) + 1)].rstrip("_")
        candidate = f"{trimmed}_{suffix}"
        if INTENT_ID_RE.fullmatch(candidate) and candidate not in seen:
            return candidate
    return ""


def _finalize_question(raw: LlmIntentQuestion, seen: set[str]) -> IntentQuestion | None:
    text = raw.text or raw.question
    question_id = slugify_intent_id(raw.id) or slugify_intent_id(text)
    if not question_id:
        return None
    question_id = _unique_slug(question_id, seen)
    if not question_id:
        return None
    options: list[dict[str, str]] = []
    option_values: set[str] = set()
    for option in raw.options:
        value = slugify_intent_id(option.value) or slugify_intent_id(option.label)
        if not value or value in option_values:
            continue
        label = option.label or value
        options.append({"value": value, "label": label})
        option_values.add(value)
    try:
        return IntentQuestion.model_validate(
            {
                "id": question_id,
                "text": text,
                "type": raw.type,
                "options": options,
                "required": raw.required,
                "rationale": raw.rationale,
            }
        )
    except ValidationError:
        return None


def finalize_intent_interview(
    raw: LlmDocumentIntentInterview,
) -> DocumentIntentInterview:
    if not raw.document_type:
        DocumentIntentInterview.model_validate(
            {"document_type": raw.document_type, "questions": []}
        )
    kept: list[IntentQuestion] = []
    seen: set[str] = set()
    for item in raw.questions:
        finalized = _finalize_question(item, seen)
        if finalized is None:
            continue
        seen.add(finalized.id)
        kept.append(finalized)
        if len(kept) >= INTENT_MAX_QUESTIONS:
            break
    return DocumentIntentInterview(document_type=raw.document_type, questions=kept)


def document_text_for_interview(sections: list[WordDocumentSection]) -> str:
    parts: list[str] = []
    for section in sections:
        heading = section.heading.strip()
        if heading:
            parts.append(heading)
        for paragraph in section.paragraphs:
            text = paragraph.text.strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def document_as_user_data(document: str) -> str:
    return f"{DOCUMENT_DATA_OPEN}\n{document}\n{DOCUMENT_DATA_CLOSE}"


def intent_interview_messages(
    *,
    prompts: dict[str, str],
    document: str,
    locale: str = "sv",
) -> list[ChatMessage]:
    return messages_with_output_contract(
        [
            {
                "role": "system",
                "content": render_prompt(
                    prompts, "expertgranskning.word.intent_interview"
                ),
            },
            {"role": "user", "content": document_as_user_data(document)},
        ],
        prompts,
    )


def _option_label(question: IntentQuestion, value: str) -> str:
    for option in question.options:
        if option.value == value:
            return option.label
    return value


REVIEW_CONTEXT_HEADING = "Structured review context"
REVIEW_CONTEXT_PERSPECTIVE = (
    "This block is the reviewer's stated perspective. "
    "It is not the document author's voice. "
    "The document may be written from a different party, objective, or concern. "
    "Treat document standpoint and reviewer standpoint as distinct. "
    "Decide what needs review and formulate questions from the answers below, "
    "not from the document's implied standpoint."
)


def render_intent_interview_section(
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
    *,
    concise: bool = False,
) -> str:
    if interview is None:
        return ""
    by_id = {answer.question_id: answer for answer in answers}
    lines = [REVIEW_CONTEXT_HEADING]
    if not concise:
        lines.append(REVIEW_CONTEXT_PERSPECTIVE)
    if interview.document_type:
        lines.append(f"Inferred document type: {interview.document_type}")
    rendered_any = False
    for question in interview.questions:
        answer = by_id.get(question.id)
        if answer is None:
            continue
        rendered = _render_answer_line(question, answer)
        if not rendered:
            continue
        lines.append("")
        lines.append(question.text)
        lines.append(rendered)
        rendered_any = True
    if not rendered_any and len(interview.questions) > 0:
        return ""
    return "\n".join(lines).strip()


def has_answered_intent(
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
) -> bool:
    """True when at least one interview question has a usable answer."""
    if interview is None:
        return False
    by_id = {answer.question_id: answer for answer in answers}
    for question in interview.questions:
        answer = by_id.get(question.id)
        if answer is None:
            continue
        if _render_answer_line(question, answer):
            return True
    return False


def _render_answer_line(question: IntentQuestion, answer: IntentAnswer) -> str:
    if question.type == "free_text" or is_custom_choice_answer(answer):
        return (answer.free_text or "").strip()
    if question.type in {"single_choice", "multi_choice"}:
        labels = [
            _option_label(question, value) for value in answer.selected_values
        ]
        return ", ".join(labels)
    raise ValueError(f"unknown question type: {question.type}")


def compose_intent_prefix(
    prompts: dict[str, str],
    *,
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
    review_intent: str,
    concise: bool = False,
) -> str:
    parts = [
        render_intent_interview_section(interview, answers, concise=concise),
        render_review_intent_message(prompts, review_intent),
    ]
    return "\n\n".join(part for part in parts if part.strip())


def compose_expert_review_context(
    prompts: dict[str, str],
    *,
    brief: str,
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
    review_intent: str,
) -> str:
    interview_section = render_intent_interview_section(interview, answers)
    if not interview_section:
        return compose_brief_with_review_intent(
            prompts, brief=brief, review_intent=review_intent
        )
    prefix = compose_intent_prefix(
        prompts,
        interview=interview,
        answers=answers,
        review_intent=review_intent,
    )
    document = (brief or "").strip()
    if not prefix:
        return document
    if not document:
        return prefix
    return f"{prefix}\n\n{document}"


async def generate_document_intent_interview(
    *,
    sections: list[WordDocumentSection],
    prompts: dict[str, str],
    locale: str = "sv",
) -> DocumentIntentInterview:
    document = document_text_for_interview(sections)
    messages = intent_interview_messages(
        prompts=prompts, document=document, locale=locale
    )
    raw = await complete_word_structured(
        messages,
        LlmDocumentIntentInterview,
        prompt_key="expertgranskning.word.intent_interview",
        prompts=prompts,
    )
    return finalize_intent_interview(raw)
