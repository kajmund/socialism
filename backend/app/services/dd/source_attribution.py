"""Source attribution for DD panel expert scores.

This module implements an explicit *attribution priority chain* — not silent
fallbacks (see repo AGENTS.md "No fallbacks"). Each step is tried in order;
the first step that yields usable evidence wins and is labeled accordingly.
If no external source is found, the badge is ``llm`` (modellbedömning) so
operators know the score rests on model reasoning alone.

Priority (highest first):
1. OKF operator manual bundle (``knowledge/manual``)
2. Web search (DuckDuckGo via ``search_duckduckgo``)
3. LLM-only — explicit label, never disguised as external fact
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.okf_corpus import search_manual
from app.services.oasis_agent_tools import search_duckduckgo

SourceKind = Literal["okf", "web", "llm"]


class SourceBadge(BaseModel):
    kind: SourceKind
    label: str = Field(min_length=1, max_length=64)
    detail: str = ""


def resolve_source_badge(
    *,
    sub_question_label: str,
    candidate_name: str,
    extra_context: str = "",
) -> SourceBadge:
    """Resolve the best available attribution badge for an expert score."""
    query = " ".join(part for part in (sub_question_label, candidate_name, extra_context) if part).strip()
    if not query:
        return SourceBadge(kind="llm", label="Modellbedömning", detail="Ingen sökfråga")

    guides = search_manual(query, limit=1)
    if guides:
        guide = guides[0]
        return SourceBadge(
            kind="okf",
            label="OKF-manual",
            detail=guide.title,
        )

    web_hits = search_duckduckgo(query, max_results=1)
    if web_hits and "error" not in web_hits[0]:
        hit = web_hits[0]
        title = str(hit.get("title") or hit.get("url") or "Webbträff").strip()
        if title:
            return SourceBadge(kind="web", label="Webb", detail=title[:200])

    return SourceBadge(
        kind="llm",
        label="Modellbedömning",
        detail="Ingen extern källa hittades — bedömningen bygger på kandidatdata och expertprofil",
    )
