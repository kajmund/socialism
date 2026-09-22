"""LLM-backed lagen.nu hit/excerpt selector. No MCP retrieval."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.session import SessionLocal
from app.llm import complete_structured_retry, invoke_structured_completer
from app.services.lagen_nu.selection import (
    HIT_ROLES,
    ExcerptDecision,
    HitDecision,
    HitRole,
    LagenNuSelectionError,
    SelectableDocument,
    SelectableHit,
    apply_hit_decisions,
    clip_selector_document,
)
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.models import ResearchContext, ResearchNeed, ResearchSourceType

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class HitDecisionModel(BaseModel):
    candidate_id: str
    keep: bool
    role: Literal[
        "named_citation",
        "travaux",
        "ratio",
        "peripheral",
        "wrong_number",
        "wrong_subject",
    ]
    pinpoint: str = ""
    excerpt_query: str = ""
    why: str = ""

    @field_validator("candidate_id", "pinpoint", "excerpt_query", "why", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class HitSelectionModel(BaseModel):
    decisions: list[HitDecisionModel] = Field(default_factory=list)


class ExcerptDecisionModel(BaseModel):
    excerpt: str
    pinpoint: str = ""
    why: str = ""

    @field_validator("excerpt", "pinpoint", "why", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class LlmLagenNuSelector:
    def __init__(
        self,
        *,
        completer: Completer | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        excerpt_system_prompt: str | None = None,
        excerpt_user_prompt: str | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._completer = completer or complete_structured_retry
        self._system_prompt = system_prompt
        self._user_prompt = user_prompt
        self._excerpt_system_prompt = excerpt_system_prompt
        self._excerpt_user_prompt = excerpt_user_prompt
        self._session_factory = session_factory or SessionLocal
        self._prompt_cache: dict[str, str] | None = None

    async def select_hits(
        self,
        *,
        need: ResearchNeed,
        source_type: ResearchSourceType,
        candidates: Sequence[SelectableHit],
        context: ResearchContext,
    ) -> list[HitDecision]:
        if not candidates:
            return []
        prompts = await self._prompts(context)
        messages = [
            {"role": "system", "content": prompts["research.lagen_nu.select.system"]},
            {
                "role": "user",
                "content": render_prompt(
                    prompts,
                    "research.lagen_nu.select.user",
                    question=need.question,
                    why_needed=need.why_needed,
                    source_type=source_type,
                    candidates_json=json.dumps(
                        [_hit_payload(item) for item in candidates],
                        ensure_ascii=False,
                    ),
                ),
            },
        ]
        parsed = await self._complete(
            messages, HitSelectionModel, prompt_key="research.lagen_nu.select.system"
        )
        decisions = [
            HitDecision(
                candidate_id=item.candidate_id,
                keep=item.keep,
                role=_role(item.role),
                pinpoint=item.pinpoint or None,
                excerpt_query=item.excerpt_query,
                why=item.why,
            )
            for item in parsed.decisions
        ]
        return apply_hit_decisions(candidates, decisions)

    async def select_excerpt(
        self,
        *,
        need: ResearchNeed,
        source_type: ResearchSourceType,
        document: SelectableDocument,
        context: ResearchContext,
    ) -> ExcerptDecision:
        prompts = await self._prompts(context)
        clipped = clip_selector_document(document.text)
        messages = [
            {"role": "system", "content": prompts["research.lagen_nu.excerpt.system"]},
            {
                "role": "user",
                "content": render_prompt(
                    prompts,
                    "research.lagen_nu.excerpt.user",
                    question=need.question,
                    why_needed=need.why_needed,
                    source_type=source_type,
                    title=document.title or "",
                    uri=document.uri,
                    identifier=document.identifier or "",
                    pinpoint=document.pinpoint or "",
                    highlight=document.highlight,
                    truncated="true" if document.truncated else "false",
                    document_text=clipped,
                ),
            },
        ]
        parsed = await self._complete(
            messages,
            ExcerptDecisionModel,
            prompt_key="research.lagen_nu.excerpt.system",
        )
        return ExcerptDecision(
            excerpt=parsed.excerpt,
            pinpoint=parsed.pinpoint or None,
            why=parsed.why,
        )

    async def _complete(
        self,
        messages: list[dict[str, Any]],
        model: type[Any],
        *,
        prompt_key: str,
    ):
        try:
            parsed = await invoke_structured_completer(
                self._completer, messages, model, prompt_key=prompt_key
            )
        except Exception as exc:
            raise LagenNuSelectionError(
                f"lagen.nu selector model call failed: {exc}"
            ) from exc
        if isinstance(parsed, model):
            return parsed
        try:
            return model.model_validate(parsed)
        except Exception as exc:
            raise LagenNuSelectionError(
                f"lagen.nu selector returned an invalid payload: {exc}"
            ) from exc

    async def _prompts(self, context: ResearchContext) -> dict[str, str]:
        if (
            self._system_prompt is not None
            and self._user_prompt is not None
            and self._excerpt_system_prompt is not None
            and self._excerpt_user_prompt is not None
        ):
            return {
                "research.lagen_nu.select.system": self._system_prompt,
                "research.lagen_nu.select.user": self._user_prompt,
                "research.lagen_nu.excerpt.system": self._excerpt_system_prompt,
                "research.lagen_nu.excerpt.user": self._excerpt_user_prompt,
            }
        if self._prompt_cache is not None:
            return self._prompt_cache
        customer_id = context.scope.customer_id
        module = context.scope.module
        if customer_id is None or not module:
            raise LagenNuSelectionError(
                "lagen.nu selector requires customer_id and module"
            )
        async with self._session_factory() as session:
            loaded = await require_active_prompts(
                session,
                customer_id=customer_id,
                module=module,
                language="sv",
            )
        required = (
            "research.lagen_nu.select.system",
            "research.lagen_nu.select.user",
            "research.lagen_nu.excerpt.system",
            "research.lagen_nu.excerpt.user",
        )
        missing = [key for key in required if not str(loaded.get(key) or "").strip()]
        if missing:
            raise LagenNuSelectionError(
                "lagen.nu selector prompts are required: " + ", ".join(missing)
            )
        self._prompt_cache = {key: loaded[key] for key in required}
        return self._prompt_cache


def _hit_payload(item: SelectableHit) -> dict[str, object]:
    return {
        "candidate_id": item.candidate_id,
        "uri": item.uri,
        "title": item.title,
        "identifier": item.identifier,
        "highlight": item.highlight,
        "pinpoint": item.pinpoint,
    }


def _role(value: str) -> HitRole:
    if value not in HIT_ROLES:
        raise LagenNuSelectionError(f"unknown selector role {value!r}")
    return value  # type: ignore[return-value]
