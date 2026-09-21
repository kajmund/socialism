"""Word structured LLM calls reuse the shared retry seam.

Does not repair JSON in code. A second syntax failure fails closed.
Retry ownership lives in ``complete_structured_retry`` — this wrapper
only supplies the Word catalog instruction and job timings.
"""

from __future__ import annotations

from app.llm import (
    ChatMessage,
    complete_structured_retry,
    is_json_syntax_validation_error,
    validation_category,
)
from app.services.expertgranskning.word_review_timing import WordReviewTimings
from app.services.prompt_catalog import render_prompt

__all__ = [
    "complete_word_structured",
    "is_json_syntax_validation_error",
    "validation_category",
]


async def complete_word_structured[T](
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    prompts: dict[str, str],
    timings: WordReviewTimings | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> T:
    return await complete_structured_retry(
        messages,
        response_model,
        retry_instruction=render_prompt(
            prompts, "expertgranskning.word.structured_retry"
        ),
        on_retry=timings.record_structured_retry if timings is not None else None,
        model=model,
        max_tokens=max_tokens,
        prompt_key="expertgranskning.word.structured_retry",
    )
