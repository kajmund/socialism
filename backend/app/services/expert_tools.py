"""Catalog and helpers for tools an expert persona may use."""

from __future__ import annotations

from typing import Any

from app.services.prompt_catalog import render_prompt

COMPANY_EXPERT_TOOLS = frozenset({"search_companies", "lookup_company", "validate_orgnr"})
SEARCH_EXPERT_TOOLS = frozenset({"search_duckduckgo", "search_wiki"})

DEFAULT_EXPERT_TOOL_IDS: tuple[str, ...] = (
    "search_companies",
    "lookup_company",
    "validate_orgnr",
    "search_duckduckgo",
    "search_wiki",
)

EXPERT_TOOL_IDS = frozenset(DEFAULT_EXPERT_TOOL_IDS)


def default_expert_tools() -> list[str]:
    return list(DEFAULT_EXPERT_TOOL_IDS)


def normalize_expert_tools(raw: list[str] | None) -> list[str]:
    """Validate and dedupe. None means the catalog default. [] means no tools."""
    if raw is None:
        return default_expert_tools()
    unknown = [name for name in raw if name not in EXPERT_TOOL_IDS]
    if unknown:
        raise ValueError(f"Unknown expert tools: {', '.join(unknown)}")
    seen: set[str] = set()
    out: list[str] = []
    for name in raw:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def resolve_expert_tools(raw: list[str] | None) -> list[str]:
    """Stored None (legacy expert row) → all catalog tools."""
    return normalize_expert_tools(raw)


def filter_openai_tools(
    specs: list[dict[str, Any]],
    allowed: frozenset[str],
) -> list[dict[str, Any]]:
    return [
        spec
        for spec in specs
        if spec.get("function", {}).get("name") in allowed
    ]


def expert_tool_prompt_extra(prompts: dict[str, str], tools: list[str]) -> str:
    names = set(tools)
    parts: list[str] = []
    if names & COMPANY_EXPERT_TOOLS:
        parts.append(render_prompt(prompts, "chat.expert.company_tools"))
    if names & SEARCH_EXPERT_TOOLS:
        parts.append(render_prompt(prompts, "chat.expert.search_tools"))
    return "\n\n".join(parts)
