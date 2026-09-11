"""Word-local structured LLM calls with one JSON-syntax retry.

Does not repair JSON in code. A second syntax failure fails closed.
"""

from __future__ import annotations

import logging
from pydantic import ValidationError

from app.llm import ChatMessage, complete_structured
from app.services.prompt_catalog import render_prompt

logger = logging.getLogger(__name__)


def is_json_syntax_validation_error(exc: ValidationError) -> bool:
    return any(error.get("type") == "json_invalid" for error in exc.errors())


def validation_category(exc: ValidationError) -> str:
    types = [error.get("type") for error in exc.errors() if error.get("type")]
    return str(types[0]) if types else "unknown"


async def complete_word_structured[T](
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    prompts: dict[str, str],
) -> T:
    try:
        return await complete_structured(messages, response_model)
    except ValidationError as exc:
        category = validation_category(exc)
        if not is_json_syntax_validation_error(exc):
            raise
        logger.info(
            "Word structured output schema=%s attempt=1 category=%s, retrying once",
            response_model.__name__,
            category,
        )
        retry = render_prompt(prompts, "expertgranskning.word.structured_retry")
        try:
            return await complete_structured(
                [*messages, {"role": "user", "content": retry}],
                response_model,
            )
        except ValidationError as retry_exc:
            logger.info(
                "Word structured output schema=%s attempt=2 category=%s",
                response_model.__name__,
                validation_category(retry_exc),
            )
            raise
