"""Plan short searches within an already resolved, truncated legal document."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from app.database.session import SessionLocal
from app.llm import complete_structured_retry, invoke_structured_completer
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.selection import LagenNuSelectionError
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.models import ResearchContext, ResearchNeed


class PassageQueries(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)

    @field_validator("queries")
    @classmethod
    def require_short_queries(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values))
        if any(not value or len(value) > 120 for value in cleaned):
            raise ValueError("passage queries must contain 1–120 characters")
        return cleaned


class PassageQueryPlanner(Protocol):
    async def plan_queries(
        self, *, need: ResearchNeed, document: LagenNuDocument, context: ResearchContext
    ) -> list[str]: ...


class LlmPassageQueryPlanner:
    def __init__(
        self,
        *,
        completer: Callable[..., Awaitable[Any]] | None = None,
        prompts: dict[str, str] | None = None,
    ) -> None:
        self._completer = completer or complete_structured_retry
        self._prompts = prompts

    async def plan_queries(
        self, *, need: ResearchNeed, document: LagenNuDocument, context: ResearchContext
    ) -> list[str]:
        prompts = self._prompts
        if prompts is None:
            if context.scope.customer_id is None or not context.scope.module:
                raise LagenNuSelectionError("Passage planning requires customer_id and module")
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
                "content": render_prompt(
                    prompts,
                    "research.lagen_nu.passage_queries.system",
                ),
            },
            {
                "role": "user",
                "content": render_prompt(
                    prompts,
                    "research.lagen_nu.passage_queries.user",
                    question=need.question,
                    document_json=json.dumps(
                        {
                            "uri": document.uri,
                            "title": document.title,
                            "truncated": document.truncated,
                        },
                        ensure_ascii=False,
                    ),
                ),
            },
        ]
        try:
            parsed = await invoke_structured_completer(
                self._completer,
                messages,
                PassageQueries,
                prompt_key="research.lagen_nu.passage_queries.system",
            )
            return PassageQueries.model_validate(parsed).queries
        except Exception as exc:
            raise LagenNuSelectionError("Passage query planning failed") from exc
