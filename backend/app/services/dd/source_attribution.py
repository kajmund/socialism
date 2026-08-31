"""Source attribution for DD panel expert scores.

This module implements an explicit *attribution priority chain* — not silent
fallbacks (see repo AGENTS.md "No fallbacks"). Each step is tried in order;
the first step that yields usable evidence wins and is labeled accordingly.
If no external source is found, the badge is ``llm`` (modellbedömning) so
operators know the score rests on model reasoning alone.

Priority (highest first):
1. Candidate figures already in the brief — labeled **Grunddata** (any
   sub-question that uses those numbers; no decorative web search)
2. An actual web/wiki tool result from the scoring turn — labeled **Webb**
3. LLM-only — explicit label, never disguised as external fact
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SourceKind = Literal["web", "llm"]


class SourceBadge(BaseModel):
    kind: SourceKind
    label: str = Field(min_length=1, max_length=64)
    detail: str = ""

    @model_validator(mode="before")
    @classmethod
    def drop_okf_kind(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("kind") != "okf":
            return data
        return {
            **data,
            "kind": "llm",
            "label": "Modellbedömning",
            "detail": "Ingen extern källa hittades — bedömningen bygger på kandidatdata och expertprofil",
        }


def resolve_source_badge(
    *,
    figures_in_brief: bool = False,
    web_detail: str = "",
) -> SourceBadge:
    """Resolve the attribution badge for an expert score.

    Do not run a parallel web search here. A DuckDuckGo hit on the sub-question
    title is not evidence — it routinely attaches the wrong company.
    """
    if figures_in_brief:
        return SourceBadge(
            kind="llm",
            label="Grunddata",
            detail="Nyckeltal från kandidatunderlaget",
        )
    detail = web_detail.strip()
    if detail:
        return SourceBadge(kind="web", label="Webb", detail=detail[:200])
    return SourceBadge(
        kind="llm",
        label="Modellbedömning",
        detail="Ingen extern källa hittades — bedömningen bygger på kandidatdata och expertprofil",
    )
