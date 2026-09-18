"""Resolve and render a compact, domain-agnostic Word review actor context.

Source material is the intent interview answers, free review intent, and
inferred document type. Document voice is never a source.
"""

from __future__ import annotations

from app.services.actor_profiles import ActorToolHandler

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
from app.services.review_contract import messages_with_output_contract

WORD_ACTOR_CONTEXT_MAX_TOKENS = 512
ACTOR_CONTEXT_HEADING = "Actor context"
INTENT_DATA_OPEN = "<intent>"
INTENT_DATA_CLOSE = "</intent>"
ACTOR_CONTEXT_KNOWN_KEY = "expertgranskning.word.actor_context.known"
ACTOR_CONTEXT_UNKNOWN_KEY = "expertgranskning.word.actor_context.unknown"


def _llm_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


class ActorContext(BaseModel):
    """Compact control signal for reviewer/actor perspective."""

    model_config = ConfigDict(extra="ignore")

    needs_actor_profile: bool = Field(
        default=False,
        description="Request get_actor_context only if a concrete uncertainty about the user/customer matters here and is not answered by the supplied context. Never for routine completeness checks.",
    )
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
    interview_section = render_intent_interview_section(interview, answers, concise=True)
    if interview_section:
        parts.append(interview_section)
    intent = (review_intent or "").strip()
    if intent:
        parts.append(f"Free review intent:\n{intent}")
    return "\n\n".join(parts)


def render_actor_context(context: ActorContext, prompts: dict[str, str]) -> str:
    """Render the high-priority actor-context block from the active prompt map."""
    if not context.perspective_known:
        return render_prompt(prompts, ACTOR_CONTEXT_UNKNOWN_KEY)
    return render_prompt(
        prompts,
        ACTOR_CONTEXT_KNOWN_KEY,
        user_role=context.user_role,
        counterpart_or_audience=context.counterpart_or_audience,
        relationship=context.relationship,
        review_goal=context.review_goal,
        output_perspective=context.output_perspective,
    )


def actor_context_messages(
    *,
    prompts: dict[str, str],
    source: str,
    locale: str = "sv",
) -> list[ChatMessage]:
    return messages_with_output_contract(
        [
            {
                "role": "system",
                "content": render_prompt(prompts, "expertgranskning.word.actor_context"),
            },
            {
                "role": "user",
                "content": f"{INTENT_DATA_OPEN}\n{source}\n{INTENT_DATA_CLOSE}",
            },
        ],
        prompts,
    )


async def resolve_actor_context(
    *,
    prompts: dict[str, str],
    interview: DocumentIntentInterview | None,
    answers: list[IntentAnswer],
    review_intent: str,
    limiter: WordReviewLimiter,
    locale: str = "sv",
    actor_profile_handler: ActorToolHandler | None = None,
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
            actor_context_messages(prompts=prompts, source=source, locale=locale),
            ActorContext,
            prompts=prompts,
            timings=limiter.timings,
            model=settings.word_review_router_model_override,
            max_tokens=(
                WORD_ACTOR_CONTEXT_MAX_TOKENS
                if settings.word_review_router_model_override
                else None
            ),
        ),
    )
    if raw.needs_actor_profile and actor_profile_handler is not None:
        import json

        profile_context = await actor_profile_handler("get_actor_context", {})
        messages = actor_context_messages(prompts=prompts, source=source, locale=locale)
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {"actor_profile_data": json.loads(profile_context)}, ensure_ascii=False
                ),
            }
        )
        raw = await limiter.run(
            "actor_context",
            lambda: complete_word_structured(
                messages,
                ActorContext,
                prompts=prompts,
                timings=limiter.timings,
                model=settings.word_review_router_model_override,
                max_tokens=WORD_ACTOR_CONTEXT_MAX_TOKENS
                if settings.word_review_router_model_override
                else None,
            ),
        )
    resolved = finalize_actor_context(raw)
    limiter.timings.record_actor_context_resolved(resolved.perspective_known)
    return resolved
