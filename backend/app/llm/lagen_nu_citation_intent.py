"""Interpret named case citations before retrieval; never infer intent from keywords."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.database.session import SessionLocal
from app.llm import complete_structured_retry, invoke_structured_completer
from app.services.lagen_nu.selection import LagenNuSelectionError
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.models import ResearchContext, ResearchNeed


class CaseCitationIntent(BaseModel):
    citation: str
    role: Literal["target", "exclude", "context"]


class CaseCitationPlan(BaseModel):
    citations: list[CaseCitationIntent]
    search_query: str = Field(max_length=180)

    def verify(self, expected: list[str]) -> CaseCitationPlan:
        actual = [item.citation for item in self.citations]
        if len(actual) != len(expected) or set(actual) != set(expected):
            raise ValueError("citation plan must classify every supplied citation exactly once")
        self.search_query = self.search_query.strip()
        if any(item.role != "target" for item in self.citations) and not self.search_query:
            raise ValueError("non-target citations require a discovery query")
        if any(
            item.role != "target" and item.citation.casefold() in self.search_query.casefold()
            for item in self.citations
        ):
            raise ValueError("discovery query must not repeat excluded or contextual citations")
        return self


class CaseCitationPlanner(Protocol):
    async def plan(
        self, *, need: ResearchNeed, citations: list[str], context: ResearchContext
    ) -> CaseCitationPlan: ...


class LlmCaseCitationPlanner:
    def __init__(
        self,
        *,
        completer: Callable[..., Awaitable[Any]] | None = None,
        prompts: dict[str, str] | None = None,
    ) -> None:
        self._completer = completer or complete_structured_retry
        self._prompts = prompts

    async def plan(
        self, *, need: ResearchNeed, citations: list[str], context: ResearchContext
    ) -> CaseCitationPlan:
        prompts = self._prompts
        if prompts is None:
            if context.scope.customer_id is None or not context.scope.module:
                raise LagenNuSelectionError("Citation planning requires customer_id and module")
            async with SessionLocal() as session:
                prompts = await require_active_prompts(
                    session,
                    customer_id=context.scope.customer_id,
                    module=context.scope.module,
                    language="sv",
                )
        messages = [
            {
                "role": "system",
                "content": render_prompt(prompts, "research.lagen_nu.citation_intent.system"),
            },
            {
                "role": "user",
                "content": render_prompt(
                    prompts,
                    "research.lagen_nu.citation_intent.user",
                    question=need.question,
                    citations_json=json.dumps(citations, ensure_ascii=False),
                ),
            },
        ]
        try:
            parsed = await invoke_structured_completer(
                self._completer,
                messages,
                CaseCitationPlan,
                prompt_key="research.lagen_nu.citation_intent.system",
            )
            return CaseCitationPlan.model_validate(parsed).verify(citations)
        except Exception as exc:
            raise LagenNuSelectionError("Case citation intent planning failed") from exc
