"""LLM-backed legal question validator. Structured output only; no retrieval."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_structured_retry, invoke_structured_completer
from app.services.lagen_nu.question_validation import (
    LegalQuestionValidationError,
    LegalQuestionValidator,
    LegalQuestionVerdict,
)
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]

LegalTrackValue = Literal["market_law", "civil_law", "mixed", "other", "unknown"]
LegalActionValue = Literal["keep", "rewrite", "split"]


class LegalQuestionValidationModel(BaseModel):
    is_coherent: bool
    issue_type: str = ""
    legal_track: LegalTrackValue = "unknown"
    institutions: list[str] = Field(default_factory=list)
    provisions: list[str] = Field(default_factory=list)
    remedy: str = ""
    problems: list[str] = Field(default_factory=list)
    action: LegalActionValue
    rewritten_question: str = ""
    split_questions: list[str] = Field(default_factory=list)
    rationale: str = ""

    @field_validator(
        "issue_type",
        "remedy",
        "rewritten_question",
        "rationale",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("institutions", "provisions", "problems", "split_questions", mode="before")
    @classmethod
    def list_of_text(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("must be a list")
        return [str(item).strip() for item in value if str(item).strip()]

    @model_validator(mode="after")
    def action_matches_coherence(self) -> LegalQuestionValidationModel:
        if self.is_coherent and self.action != "keep":
            raise ValueError("coherent questions must be kept unchanged")
        if not self.is_coherent and self.action == "keep":
            raise ValueError("incoherent questions cannot be kept")
        if self.legal_track == "mixed" and self.action == "keep":
            raise ValueError("mixed legal tracks must be rewritten or split")
        if self.action == "rewrite" and not self.rewritten_question:
            raise ValueError("rewrite requires rewritten_question")
        if self.action == "split" and len(self.split_questions) < 2:
            raise ValueError("split requires at least two split_questions")
        if self.action == "keep" and (self.rewritten_question or self.split_questions):
            raise ValueError("keep must not rewrite or split the question")
        return self


def verdict_from_model(parsed: LegalQuestionValidationModel) -> LegalQuestionVerdict:
    return LegalQuestionVerdict(
        is_coherent=parsed.is_coherent,
        issue_type=parsed.issue_type,
        legal_track=parsed.legal_track,
        institutions=tuple(parsed.institutions),
        provisions=tuple(parsed.provisions),
        remedy=parsed.remedy,
        problems=tuple(parsed.problems),
        action=parsed.action,
        rewritten_question=parsed.rewritten_question,
        split_questions=tuple(parsed.split_questions),
        rationale=parsed.rationale,
    )


class LlmLegalQuestionValidator:
    """Structured legal semantics. Never searches or fetches sources."""

    def __init__(
        self,
        *,
        completer: Completer | None = None,
        system_prompt: str,
        user_prompt: str,
    ) -> None:
        text = system_prompt.strip()
        user = user_prompt.strip()
        if not text:
            raise LegalQuestionValidationError("legal question validator prompt is required")
        if not user:
            raise LegalQuestionValidationError(
                "legal question validator user prompt is required"
            )
        self._completer = completer or complete_structured_retry
        self._system_prompt = text
        self._user_prompt = user

    async def validate(
        self,
        *,
        question: str,
        why_needed: str,
        source_types: Sequence[str],
    ) -> LegalQuestionVerdict:
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": render_prompt(
                    {"research.lagen_nu.question_validate.user": self._user_prompt},
                    "research.lagen_nu.question_validate.user",
                    question=question,
                    why_needed=why_needed,
                    source_types=", ".join(source_types),
                ),
            },
        ]
        try:
            parsed = await invoke_structured_completer(
                self._completer,
                messages,
                LegalQuestionValidationModel,
                prompt_key="research.lagen_nu.question_validate.system",
            )
        except Exception as exc:
            raise LegalQuestionValidationError(
                "legal question validator model call failed"
            ) from exc
        if not isinstance(parsed, LegalQuestionValidationModel):
            try:
                parsed = LegalQuestionValidationModel.model_validate(parsed)
            except Exception as exc:
                raise LegalQuestionValidationError(
                    "legal question validator returned an invalid payload"
                ) from exc
        return verdict_from_model(parsed)


async def build_llm_legal_question_validator(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
    completer: Completer | None = None,
) -> LegalQuestionValidator:
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module=module,
        language="sv",
    )
    return LlmLegalQuestionValidator(
        completer=completer,
        system_prompt=render_prompt(prompts, "research.lagen_nu.question_validate.system"),
        user_prompt=prompts["research.lagen_nu.question_validate.user"],
    )
