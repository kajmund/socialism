"""Resolve and render a compact, domain-agnostic Word review actor context.

Source material is the intent interview answers, free review intent, and
inferred document type. Document voice is never a source.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.llm import ChatMessage
from app.services.expertgranskning.intent_interview import (
    DocumentIntentInterview,
    IntentAnswer,
    has_answered_intent,
    render_intent_interview_section,
)
from app.services.expertgranskning.word_review_timing import WordReviewLimiter
from app.services.expertgranskning.word_structured import complete_word_structured
from app.services.prompt_catalog import render_prompt

WORD_ACTOR_CONTEXT_MAX_TOKENS = 512
ACTOR_CONTEXT_HEADING = "Actor context"
INTENT_DATA_OPEN = "<intent>"
INTENT_DATA_CLOSE = "</intent>"

PERSPECTIVE_KNOWN_INVARIANT = (
    "Perspective is known. This is perspective control, not advocacy.\n"
    "- Address recommendations and actions to the user's role.\n"
    "- You may identify the counterpart or audience's strongest argument, "
    "but label it as their perspective. Do not turn it into advice to the user.\n"
    "- Never assume the document voice equals the reviewer voice.\n"
    "- Factual or substantive criticism that is adverse to the user's position "
    "is allowed and required when warranted.\n"
    "- A weakness for the user's side remains a weakness for the user's side. "
    "Do not advise attacking, challenging, or arguing that side's case unless "
    "the user is actually on the attacking or challenging side."
)

PERSPECTIVE_UNKNOWN_INVARIANT = (
    "Perspective is unknown. Use neutral language. Do not invent a side. "
    "Do not address advice to a party the user did not claim. "
    "Do not assume the document voice is the reviewer voice."
)


def _llm_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


class ActorContext(BaseModel):
    """Compact control signal for reviewer/actor perspective."""

    model_config = ConfigDict(extra="ignore")

    user_role: str = Field(default="", description="Reviewer's role relative to the document")
    counterpart_or_audience: str = Field(
        default="",
        description="The other side or intended audience",
    )
    relationship: str = Field(
        default="",
        description="How the user relates to the document",
    )
    review_goal: str = Field(default="", description="What the review should achieve")
    output_perspective: str = Field(
        default="",
        description="How advice and recommendations should be framed",
    )
    perspective_known: bool = False

    @field_validator(
        "user_role",
        "counterpart_or_audience",
        "relationship",
        "review_goal",
        "output_perspective",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> str:
        return _llm_text(value)

    @field_validator("perspective_known", mode="before")
    @classmethod
    def coerce_known(cls, value: object) -> object:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return value


def unknown_actor_context() -> ActorContext:
    return ActorContext(perspective_known=False)


def finalize_actor_context(raw: ActorContext) -> ActorContext:
    if not raw.perspective_known or not raw.user_role:
        return unknown_actor_context()
    return ActorContext(
        user_role=raw.user_role,
        counterpart_or_audience=raw.counterpart_or_audience,
        relationship=raw.relationship,
        review_goal=raw.review_goal,
        output_perspective=raw.output_perspective,
        perspective_known=True,
    )


def has_usable_actor_source(
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
    review_intent: str,
) -> bool:
    if (review_intent or "").strip():
        return True
    return has_answered_intent(interview, answers)


def actor_context_source_text(
    *,
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
    review_intent: str,
) -> str:
    """Interview answers, free review intent, and inferred document type only."""
    parts: list[str] = []
    interview_section = render_intent_interview_section(
        interview, answers, concise=True
    )
    if interview_section:
        parts.append(interview_section)
    intent = (review_intent or "").strip()
    if intent:
        parts.append(f"Free review intent:\n{intent}")
    return "\n\n".join(parts)


def render_actor_context(context: ActorContext) -> str:
    """Server-owned high-priority system block. Never includes document body."""
    lines = [ACTOR_CONTEXT_HEADING]
    if not context.perspective_known:
        lines.append(PERSPECTIVE_UNKNOWN_INVARIANT)
        return "\n".join(lines)
    lines.append(PERSPECTIVE_KNOWN_INVARIANT)
    lines.append(f"User role: {context.user_role}")
    if context.counterpart_or_audience:
        lines.append(f"Counterpart or audience: {context.counterpart_or_audience}")
    if context.relationship:
        lines.append(f"Relationship: {context.relationship}")
    if context.review_goal:
        lines.append(f"Review goal: {context.review_goal}")
    if context.output_perspective:
        lines.append(f"Output perspective: {context.output_perspective}")
    return "\n".join(lines)


def actor_context_messages(
    *,
    prompts: dict[str, str],
    source: str,
) -> list[ChatMessage]:
    return [
        {
            "role": "system",
            "content": render_prompt(prompts, "expertgranskning.word.actor_context"),
        },
        {
            "role": "user",
            "content": f"{INTENT_DATA_OPEN}\n{source}\n{INTENT_DATA_CLOSE}",
        },
    ]


async def resolve_actor_context(
    *,
    prompts: dict[str, str],
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
    review_intent: str,
    limiter: WordReviewLimiter,
) -> ActorContext:
    """One cheap structured call when answers or free intent exist; else unknown."""
    if not has_usable_actor_source(interview, answers, review_intent):
        limiter.timings.record_actor_context_resolved(False)
        return unknown_actor_context()
    source = actor_context_source_text(
        interview=interview,
        answers=answers,
        review_intent=review_intent,
    )
    raw = await limiter.run(
        "actor_context",
        lambda: complete_word_structured(
            actor_context_messages(prompts=prompts, source=source),
            ActorContext,
            prompts=prompts,
            timings=limiter.timings,
            model=settings.word_review_router_model,
            max_tokens=WORD_ACTOR_CONTEXT_MAX_TOKENS,
        ),
    )
    resolved = finalize_actor_context(raw)
    limiter.timings.record_actor_context_resolved(resolved.perspective_known)
    return resolved
