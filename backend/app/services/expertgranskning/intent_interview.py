"""Generate and compose a generic document-driven intent interview."""

from __future__ import annotations

from app.llm import ChatMessage
from app.services.expertgranskning.schemas import (
    DocumentIntentInterview,
    IntentAnswer,
    IntentQuestion,
    WordDocumentSection,
)
from app.services.expertgranskning.word_structured import complete_word_structured
from app.services.panel.review_intent import (
    compose_brief_with_review_intent,
    render_review_intent_message,
)
from app.services.prompt_catalog import render_prompt


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


def _option_label(question: IntentQuestion, value: str) -> str:
    for option in question.options:
        if option.value == value:
            return option.label
    return value


def render_intent_interview_section(
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
) -> str:
    if interview is None:
        return ""
    by_id = {answer.question_id: answer for answer in answers}
    lines = ["Structured review context"]
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


def _render_answer_line(question: IntentQuestion, answer: IntentAnswer) -> str:
    if question.type == "free_text":
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
) -> str:
    parts = [
        render_intent_interview_section(interview, answers),
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
) -> DocumentIntentInterview:
    document = document_text_for_interview(sections)
    user = render_prompt(prompts, "expertgranskning.word.intent_interview")
    messages: list[ChatMessage] = []
    if document:
        messages.append({"role": "system", "content": document})
    messages.append({"role": "user", "content": user})
    return await complete_word_structured(
        messages,
        DocumentIntentInterview,
        prompts=prompts,
    )
