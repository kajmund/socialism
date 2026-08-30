"""Expert tool catalog and prompt extras."""

from __future__ import annotations

import pytest

from app.services.expert_tools import (
    DEFAULT_EXPERT_TOOL_IDS,
    expert_tool_prompt_extra,
    filter_openai_tools,
    normalize_expert_tools,
)
from app.services.prompt_catalog import default_prompts


def test_normalize_none_is_catalog_default():
    assert normalize_expert_tools(None) == list(DEFAULT_EXPERT_TOOL_IDS)


def test_normalize_empty_is_no_tools():
    assert normalize_expert_tools([]) == []


def test_normalize_rejects_unknown():
    with pytest.raises(ValueError, match="not_a_tool"):
        normalize_expert_tools(["search_wiki", "not_a_tool"])


def test_filter_openai_tools():
    specs = [
        {"type": "function", "function": {"name": "search_wiki"}},
        {"type": "function", "function": {"name": "lookup_company"}},
    ]
    filtered = filter_openai_tools(specs, frozenset({"lookup_company"}))
    assert [row["function"]["name"] for row in filtered] == ["lookup_company"]


def test_prompt_extra_only_includes_selected_groups():
    prompts = default_prompts("sv")
    company_only = expert_tool_prompt_extra(prompts, ["lookup_company"])
    assert "search_companies" in company_only
    assert "search_duckduckgo" not in company_only

    search_only = expert_tool_prompt_extra(prompts, ["search_wiki"])
    assert "search_wiki" in search_only
    assert "search_companies" not in search_only

    assert expert_tool_prompt_extra(prompts, []) == ""
