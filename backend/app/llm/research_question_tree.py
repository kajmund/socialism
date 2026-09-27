"""Generative question-tree operations. Jev remains the controller."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import complete_structured_retry, invoke_structured_completer
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.question_tree import (
    AnswerInput,
    GeneratedAnswer,
    GeneratedQuestion,
)

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class QuestionRows(BaseModel):
    questions: list[str] = Field(default_factory=list)

    @field_validator("questions", mode="before")
    @classmethod
    def clean_questions(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("questions must be a list")
        return [" ".join(str(item).split()) for item in value if str(item).strip()]


class AnswerRow(BaseModel):
    answer: str
    status: str


class LlmQuestionTreeGenerator:
    def __init__(
        self,
        *,
        prompts: dict[str, str],
        completer: Completer | None = None,
    ) -> None:
        self.prompts = prompts
        self.completer = completer or complete_structured_retry
        self.model_provider = settings.llm_provider
        self.model = settings.selected_llm_model

    async def decompose(self, *, question: str) -> Sequence[GeneratedQuestion]:
        parsed = await self._complete(
            "research.decomposition",
            QuestionRows,
            question=question,
        )
        return [GeneratedQuestion(question=item) for item in parsed.questions]

    async def formulate_gap_questions(
        self,
        *,
        question: str,
        answer: str,
        child_answers: Sequence[AnswerInput],
        gap_noul: dict[str, float],
    ) -> Sequence[GeneratedQuestion]:
        parsed = await self._complete(
            "research.gap_questions",
            QuestionRows,
            question=question,
            answer=answer,
            child_answers_json=_answers_json(child_answers),
            gap_noul_json=json.dumps(gap_noul, ensure_ascii=False),
        )
        return [GeneratedQuestion(question=item) for item in parsed.questions]

    async def synthesize_leaf(
        self,
        *,
        question: str,
        evidence: Sequence[Any],
    ) -> GeneratedAnswer:
        started = time.perf_counter()
        parsed = await self._complete(
            "research.leaf_answer",
            AnswerRow,
            question=question,
            evidence_json=json.dumps(
                [
                    {
                        "id": item.id,
                        "status": item.status,
                        "title": item.title,
                        "excerpt": item.excerpt,
                        "locator": item.locator,
                    }
                    for item in evidence
                ],
                ensure_ascii=False,
            ),
        )
        return GeneratedAnswer(
            text=parsed.answer,
            status=_answer_status(parsed.status),
            model_provider=settings.llm_provider,
            model=settings.selected_llm_model,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    async def synthesize_parent(
        self,
        *,
        question: str,
        child_answers: Sequence[AnswerInput],
    ) -> GeneratedAnswer:
        started = time.perf_counter()
        parsed = await self._complete(
            "research.parent_synthesis",
            AnswerRow,
            question=question,
            child_answers_json=_answers_json(child_answers),
        )
        return GeneratedAnswer(
            text=parsed.answer,
            status=_answer_status(parsed.status),
            model_provider=settings.llm_provider,
            model=settings.selected_llm_model,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    async def _complete(
        self,
        prefix: str,
        response_model: type[Any],
        **values: object,
    ) -> Any:
        system_key = f"{prefix}.system"
        user_key = f"{prefix}.user"
        messages = [
            {"role": "system", "content": render_prompt(self.prompts, system_key)},
            {
                "role": "user",
                "content": render_prompt(self.prompts, user_key, **values),
            },
        ]
        return await invoke_structured_completer(
            self.completer,
            messages,
            response_model,
            prompt_key=system_key,
        )


def _answers_json(answers: Sequence[AnswerInput]) -> str:
    return json.dumps(
        [
            {
                "answer_id": item.answer_id,
                "question": item.question,
                "answer": item.answer,
                "status": item.status,
            }
            for item in answers
        ],
        ensure_ascii=False,
    )


def _answer_status(value: str) -> str:
    if value in {"answered", "answered_with_gaps", "insufficient_evidence"}:
        return value
    raise ValueError(f"Unknown question answer status: {value}")


async def build_llm_question_tree_generator(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
) -> LlmQuestionTreeGenerator:
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module=module,
        language="sv",
    )
    return LlmQuestionTreeGenerator(prompts=prompts)
