"""Structured domain extraction from a retrieved lagen.nu document."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.session import SessionLocal
from app.llm import complete_structured_retry
from app.llm.runtime_override import bound_llm_prompt
from app.services.legal_research_result import (
    CaseLawAnalysis,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
    PreparatoryWorkAnalysis,
    StatuteAnalysis,
)
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.models import ResearchContext

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class LegalDomainExtractionError(Exception):
    """The model could not produce a verified interpretation of this document."""


class LegalInterpretation(BaseModel):
    relation: LegalQuestionRelation
    case_law: CaseLawAnalysis | None = None
    preparatory_work: PreparatoryWorkAnalysis | None = None
    statute: StatuteAnalysis | None = None

    @model_validator(mode="after")
    def one_analysis(self) -> LegalInterpretation:
        if (
            sum(item is not None for item in (self.case_law, self.preparatory_work, self.statute))
            != 1
        ):
            raise ValueError("exactly one analysis is required")
        return self


class LegalInterpreter(Protocol):
    async def interpret(
        self,
        *,
        source: LegalSourceIdentity,
        question: str,
        raw_text: str,
        truncated: bool,
        context: ResearchContext,
    ) -> LegalResearchResult: ...


class LlmLegalInterpreter:
    def __init__(
        self,
        *,
        completer: Completer | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._completer = completer or complete_structured_retry
        self._session_factory = session_factory or SessionLocal

    async def interpret(
        self,
        *,
        source: LegalSourceIdentity,
        question: str,
        raw_text: str,
        truncated: bool,
        context: ResearchContext,
    ) -> LegalResearchResult:
        customer_id = context.scope.customer_id
        module = context.scope.module
        if customer_id is None or not module:
            raise ValueError("legal interpreter requires customer_id and module")
        async with self._session_factory() as session:
            prompts = await require_active_prompts(
                session, customer_id=customer_id, module=module, language="sv"
            )
        messages = [
            {
                "role": "system",
                "content": render_prompt(prompts, "research.lagen_nu.domain.system"),
            },
            {
                "role": "user",
                "content": render_prompt(
                    prompts,
                    "research.lagen_nu.domain.user",
                    question=question,
                    source_kind=source.kind,
                    source_uri=source.canonical_uri,
                    source_text=raw_text,
                ),
            },
        ]
        try:
            with bound_llm_prompt("research.lagen_nu.domain.system"):
                parsed = LegalInterpretation.model_validate(
                    await self._completer(messages, LegalInterpretation)
                )
            return LegalResearchResult(
                source=source,
                relation=parsed.relation,
                case_law=parsed.case_law,
                preparatory_work=parsed.preparatory_work,
                statute=parsed.statute,
                raw_text=raw_text,
                truncated=truncated,
            )
        except Exception as exc:
            raise LegalDomainExtractionError("legal domain extraction failed") from exc
