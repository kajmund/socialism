"""LLM-backed ResearchPlanner using complete_structured. No retrieval."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_structured_retry
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.planner import (
    ResearchNeedDraft,
    ResearchObjective,
    ResearchPlannerError,
)
from app.services.research.registry import production_registered_source_types

Completer = Callable[[list[dict[str, Any]], type[Any]], Awaitable[Any]]


class PlannedNeedModel(BaseModel):
    question: str
    why_needed: str
    source_types: list[str] = Field(default_factory=list)
    id: str = ""

    @field_validator("question", "why_needed", "id", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("source_types", mode="before")
    @classmethod
    def list_of_text(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("must be a list")
        return [str(item).strip() for item in value if str(item).strip()]


class PlannedResearchModel(BaseModel):
    needs: list[PlannedNeedModel] = Field(default_factory=list)


def _objective_payload(objective: ResearchObjective) -> dict[str, object]:
    return {
        "objective": objective.objective,
        "context": dict(objective.context),
    }


def _drafts_from_model(parsed: PlannedResearchModel) -> list[ResearchNeedDraft]:
    drafts: list[ResearchNeedDraft] = []
    for row in parsed.needs:
        drafts.append(
            ResearchNeedDraft(
                question=row.question,
                why_needed=row.why_needed,
                source_types=list(row.source_types),  # type: ignore[arg-type]
                proposed_id=row.id,
            )
        )
    return drafts


def _require_source_types(values: Sequence[str]) -> tuple[str, ...]:
    types = tuple(str(item).strip() for item in values if str(item).strip())
    if not types:
        raise ResearchPlannerError("no executable research source types are available")
    return types


class LlmResearchPlanner:
    """Structured-output planner. Never retrieves, selects experts, or reports."""

    def __init__(
        self,
        *,
        completer: Completer | None = None,
        system_prompt: str,
        user_prompt: str,
        source_types: Sequence[str],
    ) -> None:
        text = system_prompt.strip()
        user = user_prompt.strip()
        if not text:
            raise ResearchPlannerError("research planner prompt is required")
        if not user:
            raise ResearchPlannerError("research planner user prompt is required")
        self._completer = completer or complete_structured_retry
        self._system_prompt = text
        self._user_prompt = user
        self._source_types = _require_source_types(source_types)

    async def plan_research(
        self,
        *,
        objective: ResearchObjective,
        available_source_types: Sequence[str] | None = None,
    ) -> Sequence[ResearchNeedDraft]:
        types = (
            _require_source_types(available_source_types)
            if available_source_types is not None
            else self._source_types
        )
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": render_prompt(
                    {"research.planner.user": self._user_prompt},
                    "research.planner.user",
                    source_types=", ".join(types),
                    objective=objective.objective,
                    objective_json=json.dumps(
                        _objective_payload(objective), ensure_ascii=False
                    ),
                    context_json=json.dumps(objective.context, ensure_ascii=False),
                ),
            },
        ]
        try:
            parsed = await self._completer(messages, PlannedResearchModel)
        except Exception as exc:
            raise ResearchPlannerError("Research planner model call failed") from exc
        if not isinstance(parsed, PlannedResearchModel):
            try:
                parsed = PlannedResearchModel.model_validate(parsed)
            except Exception as exc:
                raise ResearchPlannerError(
                    "Research planner returned an invalid payload"
                ) from exc
        return _drafts_from_model(parsed)


async def build_llm_research_planner(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
) -> LlmResearchPlanner:
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module=module,
        language="sv",
    )
    return LlmResearchPlanner(
        system_prompt=render_prompt(prompts, "research.planner.system"),
        user_prompt=prompts["research.planner.user"],
        source_types=production_registered_source_types(),
    )
