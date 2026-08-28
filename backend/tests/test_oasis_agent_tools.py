"""Unit tests for optional OASIS population agent toolkits."""

from unittest.mock import MagicMock

from app.schemas.domain import OasisRunOptions
from app.services.oasis_agent_tools import (
    SEARCH_TOOL_NAMES,
    apply_population_agent_tools,
    build_population_extra_tools,
    population_agent_max_iteration,
    population_tool_rules,
    run_search_tool,
    search_tool_specs,
)
from app.services.oasis_profiles import build_user_char
from app.services.oasis_run import parse_oasis_options
from app.services.prompt_catalog import default_prompts
from tests.test_oasis_actions_readback import _member

_PROMPTS = default_prompts("sv")


def test_parse_oasis_options_tool_defaults():
    opts = parse_oasis_options(None)
    assert opts.enable_search_duckduckgo is False
    assert opts.enable_search_wiki is False
    assert opts.enable_sympy_tools is False


def test_parse_oasis_options_tool_flags():
    opts = parse_oasis_options(
        {
            "enable_search_duckduckgo": True,
            "enable_search_wiki": True,
            "enable_sympy_tools": True,
        }
    )
    assert opts.enable_search_duckduckgo is True
    assert opts.enable_search_wiki is True
    assert opts.enable_sympy_tools is True


def test_parse_oasis_options_legacy_web_search():
    opts = parse_oasis_options(
        {
            "enable_web_search": True,
            "enable_sympy_tools": True,
        }
    )
    assert opts.enable_search_duckduckgo is True
    assert opts.enable_search_wiki is True
    assert opts.enable_sympy_tools is True
    dumped = opts.model_dump()
    assert "enable_web_search" not in dumped


def test_parse_oasis_options_legacy_does_not_override_explicit():
    opts = parse_oasis_options(
        {
            "enable_web_search": True,
            "enable_search_duckduckgo": False,
            "enable_search_wiki": True,
        }
    )
    assert opts.enable_search_duckduckgo is False
    assert opts.enable_search_wiki is True


def test_population_agent_max_iteration():
    assert population_agent_max_iteration(OasisRunOptions()) == 1
    assert (
        population_agent_max_iteration(
            OasisRunOptions(enable_search_duckduckgo=True)
        )
        == 5
    )
    assert (
        population_agent_max_iteration(
            OasisRunOptions(enable_search_wiki=True)
        )
        == 5
    )
    assert (
        population_agent_max_iteration(
            OasisRunOptions(enable_sympy_tools=True)
        )
        == 5
    )


def test_build_population_extra_tools_empty_when_disabled():
    assert build_population_extra_tools(OasisRunOptions()) == []


def test_build_population_extra_tools_search_both():
    tools = build_population_extra_tools(
        OasisRunOptions(
            enable_search_duckduckgo=True,
            enable_search_wiki=True,
        )
    )
    assert len(tools) == 2
    names = {tool.__name__ for tool in tools}
    assert names == {"search_duckduckgo", "search_wiki"}


def test_build_population_extra_tools_search_wiki_only():
    tools = build_population_extra_tools(
        OasisRunOptions(enable_search_wiki=True)
    )
    assert len(tools) == 1
    assert tools[0].__name__ == "search_wiki"


def test_build_population_extra_tools_search_ddg_only():
    tools = build_population_extra_tools(
        OasisRunOptions(enable_search_duckduckgo=True)
    )
    assert len(tools) == 1
    assert tools[0].__name__ == "search_duckduckgo"


def test_build_population_extra_tools_sympy():
    tools = build_population_extra_tools(
        OasisRunOptions(enable_sympy_tools=True)
    )
    assert len(tools) == 26


def test_sympy_series_expansion_has_param_descriptions():
    """Broken upstream docstring must not ship tools without param docs."""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tools = build_population_extra_tools(
            OasisRunOptions(enable_sympy_tools=True)
        )

    series_warns = [
        w for w in caught if "series_expansion" in str(w.message)
    ]
    assert series_warns == []

    series = next(
        t for t in tools if getattr(t, "func", t).__name__ == "series_expansion"
    )
    props = series.get_openai_tool_schema()["function"]["parameters"]["properties"]
    for name in ("expression", "variable", "point", "order"):
        assert name in props
        assert props[name].get("description"), name


def test_population_tool_rules_in_user_char():
    text = build_user_char(
        _member(),
        prompts=_PROMPTS,
        oasis_options=OasisRunOptions(
            enable_search_duckduckgo=True,
            enable_search_wiki=True,
            enable_sympy_tools=True,
        ),
    )
    assert "VERKTYG (använd när relevant" in text
    assert "search_duckduckgo" in text
    assert "search_wiki" in text
    assert "SymPy" in text
    assert "INNAN du väljer social åtgärd" in text
    assert population_tool_rules(OasisRunOptions()) == ""


def test_population_tool_rules_wiki_only():
    text = population_tool_rules(OasisRunOptions(enable_search_wiki=True))
    assert "search_wiki" in text
    assert "search_duckduckgo" not in text
    assert "SymPy" not in text


def test_search_toolkit_runtime_dependencies():
    import importlib.util

    assert importlib.util.find_spec("ddgs") is not None
    assert importlib.util.find_spec("wikipedia") is not None


def test_search_tool_specs_match_population_search_tools():
    names = {
        spec["function"]["name"]
        for spec in search_tool_specs()
        if spec.get("function")
    }
    assert names == SEARCH_TOOL_NAMES
    assert names == {"search_duckduckgo", "search_wiki"}


def test_run_search_wiki_tool():
    assert "Tom" in run_search_tool("search_wiki", {"entity": "  "})


def test_run_search_duckduckgo_tool():
    out = run_search_tool("search_duckduckgo", {"query": " "})
    assert "error" in out


def test_run_search_duckduckgo_accepts_max_results_alias(monkeypatch):
    seen: dict[str, object] = {}

    def _fake(query: str, number_of_result_pages: int = 5):
        seen["query"] = query
        seen["pages"] = number_of_result_pages
        return [{"title": "Ok"}]

    monkeypatch.setattr(
        "app.services.oasis_agent_tools.search_duckduckgo",
        _fake,
    )
    out = run_search_tool(
        "search_duckduckgo",
        {"query": "Spotify", "max_results": 1},
    )
    assert "Ok" in out
    assert seen["query"] == "Spotify"
    assert seen["pages"] == 1


def test_search_wiki_rejects_empty():
    from app.services.oasis_agent_tools import search_wiki

    assert "Tom" in search_wiki("  ")


def test_search_duckduckgo_rejects_empty():
    from app.services.oasis_agent_tools import search_duckduckgo

    out = search_duckduckgo(" ")
    assert len(out) == 1
    assert "error" in out[0]


def test_apply_population_agent_tools_skips_injectors():
    agent_graph = MagicMock()
    population_agent = MagicMock()
    injector_agent = MagicMock()
    agent_graph.get_agents.return_value = [
        (0, injector_agent),
        (1, population_agent),
    ]
    options = OasisRunOptions(enable_search_duckduckgo=True)

    apply_population_agent_tools(agent_graph, {1}, options)

    injector_agent.add_tools.assert_not_called()
    population_agent.add_tools.assert_called_once()
    assert population_agent.max_iteration == 5
