"""Short Snabb-model phrases for listener cues and tool progress."""

from __future__ import annotations

import logging
from typing import Literal

from openai import APITimeoutError, OpenAIError
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.llm import complete_structured
from app.llm.structured_retry import StructuredOutputError
from app.services.expert_reasoning import bound_expert_profile

_PHRASE_ERRORS = (
    TimeoutError,
    APITimeoutError,
    OpenAIError,
    StructuredOutputError,
    ValidationError,
)

logger = logging.getLogger(__name__)

LISTENER_PROMPT_KEY = "chat.expert.live_speech_listener"
PROGRESS_PROMPT_KEY = "chat.expert.live_speech_progress"
BACKCHANNEL_PROMPT_KEY = "chat.expert.live_speech_backchannel"
OPENING_PROMPT_KEY = "chat.expert.live_speech_opening"


class SpeechPhrase(BaseModel):
    phrase: str = ""
    silence: bool = False


class BackchannelDecision(BaseModel):
    classification: Literal[
        "backchannel", "interruption", "new_question", "uncertain"
    ] = "uncertain"


class ProgressContext(BaseModel):
    kind: str
    tool_name: str = ""
    remaining: int = 0
    summary: str = ""
    spoken: str = ""
    user_text: str = Field(default="", max_length=2000)


async def generate_opening_phrase(
    prompt: str,
    turns: tuple[tuple[str, str], ...],
) -> str | None:
    if not turns:
        user = "No previous turns."
    else:
        lines = "\n".join(f"{role}: {content}" for role, content in turns)
        user = f"Latest conversation:\n{lines}"
    return await _phrase(prompt, user, OPENING_PROMPT_KEY, max_words=32, max_tokens=120)


async def generate_listener_phrase(
    prompt: str,
    *,
    partial: str,
    spoken: str,
) -> str | None:
    user = f"Partial transcript:\n{partial}\nAlready spoken:\n{spoken or '(none)'}"
    return await _phrase(prompt, user, LISTENER_PROMPT_KEY, max_words=3)


async def generate_progress_phrase(prompt: str, context: ProgressContext) -> str | None:
    user = (
        f"kind={context.kind}\ntool={context.tool_name}\nremaining={context.remaining}\n"
        f"summary:\n{context.summary or '(none)'}\n"
        f"already spoken:\n{context.spoken or '(none)'}\n"
        f"user:\n{context.user_text or '(none)'}"
    )
    return await _phrase(prompt, user, PROGRESS_PROMPT_KEY, max_words=24)


async def classify_backchannel_llm(prompt: str, text: str) -> str:
    if not prompt.strip() or not text.strip():
        return "uncertain"
    try:
        with bound_expert_profile("fast"):
            result = await complete_structured(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
                BackchannelDecision,
                prompt_key=BACKCHANNEL_PROMPT_KEY,
                max_tokens=40,
                timeout=min(0.35, settings.live_speech_phrase_timeout_seconds),
            )
    except _PHRASE_ERRORS:
        logger.info("live_speech.backchannel_llm_failed")
        return "uncertain"
    return result.classification


async def _phrase(
    prompt: str,
    user: str,
    prompt_key: str,
    *,
    max_words: int,
    max_tokens: int = 80,
) -> str | None:
    if not prompt.strip():
        return None
    try:
        with bound_expert_profile("fast"):
            result = await complete_structured(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user},
                ],
                SpeechPhrase,
                prompt_key=prompt_key,
                max_tokens=max_tokens,
                timeout=settings.live_speech_phrase_timeout_seconds,
            )
    except _PHRASE_ERRORS:
        logger.info("live_speech.phrase_failed key=%s", prompt_key)
        return None
    if result.silence:
        return None
    words = result.phrase.strip().split()
    if not words:
        return None
    return " ".join(words[:max_words])
