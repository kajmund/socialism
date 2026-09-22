"""Word structured LLM calls reuse the shared retry seam.

Does not repair JSON in code. A second syntax failure fails closed.
Retry ownership lives in ``complete_structured_retry`` — this wrapper
only supplies the Word catalog instruction and job timings.
The task ``prompt_key`` selects the LLM configuration; the retry catalog
key is only the repair instruction.
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

WORD_STRUCTURED_RETRY_KEY = "expertgranskning.word.structured_retry"

__all__ = [
    "WORD_STRUCTURED_RETRY_KEY",
    "complete_word_structured",
    "is_json_syntax_validation_error",
    "validation_category",
]


async def complete_word_structured[T](
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    prompt_key: str,
    prompts: dict[str, str],
    timings: WordReviewTimings | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> T:
    return await complete_structured_retry(
        messages,
        response_model,
        retry_instruction=render_prompt(prompts, WORD_STRUCTURED_RETRY_KEY),
        on_retry=timings.record_structured_retry if timings is not None else None,
        model=model,
        max_tokens=max_tokens,
        prompt_key=prompt_key,
    )
