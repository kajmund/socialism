"""Optional CAMEL toolkits for OASIS population agents (search, SymPy).

Web search uses our wrappers rather than CAMEL SearchToolkit:
- ``duckduckgo-search`` was renamed/frozen to ``ddgs`` and silently returns [].
- ``wikipedia`` needs an identifiable User-Agent or the API returns 403/empty
  (JSONDecodeError). Wiki is also page-title oriented — long news queries fail.
"""

from __future__ import annotations

import json
from typing import Any

from app.schemas.domain import OasisRunOptions

SEARCH_TOOL_NAMES = frozenset({"search_duckduckgo", "search_wiki"})

# OASIS cookbook examples use max_iteration=5 when agents have external tools.
_TOOL_MAX_ITERATION = 5

_WIKI_USER_AGENT = (
    "Opinionssimulator/0.1 (internal political messaging simulator; "
    "local research tool)"
)

# CAMEL's upstream docstring for series_expansion breaks Google-style parsing
# (continuation line for `order` is under-indented), so FunctionTool emits
# UserWarnings and the LLM gets params without descriptions. Patch before wrap.
_SERIES_EXPANSION_DOC = """\
Expands an expression into a Taylor series around a given point up to a
specified order.

Args:
    expression (str): The mathematical expression to expand, provided as a
        string.
    variable (str): The variable with respect to which the series expansion
        is performed.
    point (float): The point around which the Taylor series is expanded.
    order (int): The order up to which the series expansion is computed.

Returns:
    str: JSON string containing the Taylor series expansion of the
        expression in the \"result\" field. If an error occurs, the JSON
        string will include an \"error\" field with the corresponding error
        message.
"""


def _patch_sympy_series_expansion_doc() -> None:
    from camel.toolkits.sympy_toolkit import SymPyToolkit

    SymPyToolkit.series_expansion.__doc__ = _SERIES_EXPANSION_DOC


def _any_agent_tools(options: OasisRunOptions) -> bool:
    return (
        options.enable_search_duckduckgo
        or options.enable_search_wiki
        or options.enable_sympy_tools
    )


def population_agent_max_iteration(options: OasisRunOptions) -> int:
    if _any_agent_tools(options):
        return _TOOL_MAX_ITERATION
    return 1


def search_wiki(entity: str) -> str:
    """Search Swedish Wikipedia for a named entity and return a short summary.

    Args:
        entity (str): Short page title or proper name only (e.g.
            \"Sverigedemokraterna\", \"gängkriminalitet\", \"visitationszon\").
            Do not pass long news-style search queries.

    Returns:
        str: Summary text, or a short Swedish error if no page matches.
    """
    import wikipedia
    from wikipedia.exceptions import (
        DisambiguationError,
        PageError,
        WikipediaException,
    )

    wikipedia.set_user_agent(_WIKI_USER_AGENT)
    wikipedia.set_lang("sv")
    title = (entity or "").strip()
    if not title:
        return "Tom Wikipedia-fråga — ange ett kort namn eller begrepp."

    try:
        return wikipedia.summary(title, sentences=5, auto_suggest=False)
    except DisambiguationError as e:
        option = e.options[0] if e.options else None
        if not option:
            return (
                f"Wikipedia har flera träffar för \"{title}\" men inget "
                "tydligt alternativ. Ange ett mer specifikt namn."
            )
        try:
            return wikipedia.summary(option, sentences=5, auto_suggest=False)
        except WikipediaException as nested:
            return f"Wikipedia-sökning misslyckades: {nested}"
    except PageError:
        try:
            hits = wikipedia.search(title, results=5)
        except WikipediaException as e:
            return f"Wikipedia-sökning misslyckades: {e}"
        if not hits:
            return (
                f"Ingen Wikipedia-sida för \"{title}\". Använd ett kort "
                "namn/begrepp, eller webbsök för nyheter."
            )
        try:
            return wikipedia.summary(hits[0], sentences=5, auto_suggest=False)
        except WikipediaException as e:
            return f"Wikipedia-sökning misslyckades: {e}"
    except WikipediaException as e:
        return f"Wikipedia-sökning misslyckades: {e}"
    except Exception as e:
        # Empty/403 API bodies surface as JSONDecodeError from the wikipedia lib.
        return f"Wikipedia-sökning misslyckades: {e}"


def search_duckduckgo(
    query: str,
    number_of_result_pages: int = 5,
) -> list[dict[str, Any]]:
    """Search the web via DuckDuckGo (Swedish region) for news and facts.

    Args:
        query (str): Search query (news, laws, figures, current events).
        number_of_result_pages (int): Max results to return (default 5).

    Returns:
        list[dict]: Each item has result_id, title, description, url.
            On failure, a single dict with an \"error\" key.
    """
    from ddgs import DDGS

    q = (query or "").strip()
    if not q:
        return [{"error": "Tom sökfråga."}]

    max_results = max(1, min(int(number_of_result_pages), 10))
    try:
        raw = list(
            DDGS().text(q, max_results=max_results, region="se-sv")
        )
    except Exception as e:
        return [{"error": f"duckduckgo search failed: {e}"}]

    responses: list[dict[str, Any]] = []
    for i, result in enumerate(raw, start=1):
        responses.append(
            {
                "result_id": i,
                "title": result.get("title"),
                "description": result.get("body"),
                "url": result.get("href"),
            }
        )
    if not responses:
        return [
            {
                "error": (
                    "Inga DuckDuckGo-träffar. Prova en kortare eller mer "
                    "konkret fråga."
                )
            }
        ]
    return responses


def search_tool_specs() -> list[dict[str, Any]]:
    """OpenAI tool specs for the same search functions population agents can get."""
    return [
        {
            "type": "function",
            "function": {
                "name": "search_duckduckgo",
                "description": (
                    "Search the web via DuckDuckGo (Swedish region) for news and facts."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Search query (news, laws, figures, current events)."
                            ),
                        },
                        "number_of_result_pages": {
                            "type": "integer",
                            "description": "Max results to return (default 5).",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_wiki",
                "description": (
                    "Search Swedish Wikipedia for a named entity and return a short summary."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "string",
                            "description": (
                                "Short page title or proper name only "
                                '(e.g. "Sverigedemokraterna", "gängkriminalitet").'
                            ),
                        },
                    },
                    "required": ["entity"],
                },
            },
        },
    ]


def run_search_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "search_wiki":
        return search_wiki(str(arguments.get("entity") or ""))
    if name == "search_duckduckgo":
        kwargs: dict[str, Any] = {}
        pages = arguments.get("number_of_result_pages")
        if pages is None:
            pages = arguments.get("max_results")
        if pages is not None:
            kwargs["number_of_result_pages"] = int(pages)
        result = search_duckduckgo(str(arguments.get("query") or ""), **kwargs)
        return json.dumps(result, ensure_ascii=False)
    raise ValueError(f"Unknown search tool: {name}")


def build_population_extra_tools(options: OasisRunOptions) -> list[Any]:
    """Return CAMEL tools to attach to population agents (empty if all disabled)."""
    tools: list[Any] = []
    if options.enable_search_duckduckgo:
        tools.append(search_duckduckgo)
    if options.enable_search_wiki:
        tools.append(search_wiki)
    if options.enable_sympy_tools:
        from camel.toolkits import SymPyToolkit

        _patch_sympy_series_expansion_doc()
        tools.extend(SymPyToolkit().get_tools())
    return tools


def population_tool_rules(options: OasisRunOptions) -> str:
    """Swedish guidance appended to population user_char when tools are enabled."""
    if not _any_agent_tools(options):
        return ""

    lines: list[str] = [
        "Du har externa verktyg aktiverade. Använd dem INNAN du väljer "
        "social åtgärd (comment/create_post) när flödet kräver fakta eller "
        "räkning — gissa inte om siffror, lagar, händelser eller vad något "
        "begrepp betyder.",
        "Typiska skäl att använda verktyg i den här typen av debatt:",
        "- Nyhetsinlägg med påståenden om brott, domar, belopp eller platser.",
        "- Politiska förslag med skatt, budget, procent eller \"dubbla straff\".",
        "- När du vill ifrågasätta eller bekräfta ett tal någon annan skrivit.",
        "- När du känner dig osäker — sök eller räkna först, reagera sedan.",
    ]
    if options.enable_search_wiki:
        lines.append(
            "- Wikipedia (search_wiki): BARA korta namn/begrepp som kan vara "
            "en uppslagssida (t.ex. \"Sverigedemokraterna\", \"visitationszon\", "
            "\"gängkriminalitet\"). Skicka aldrig långa nyhetsfrågor till wiki."
        )
    if options.enable_search_duckduckgo:
        lines.append(
            "- Webb (search_duckduckgo): aktuella nyheter, åtgärdspaket, "
            "lagförslag och siffror. Sök på det konkreta (plats, lag, årtal) "
            "— inte bara partinamnet."
        )
    if options.enable_sympy_tools:
        lines.append(
            "- SymPy: när du behöver räkna procent, skillnad, \"dubbelt\", "
            "kronor per månad/invånare eller enkla uttryck. Räkna först; "
            "skriv resultatet kort i din egen röst i kommentaren."
        )
    lines.append(
        "Efter verktygsanrop: välj like, dislike, comment eller create_post. "
        "Klistra inte in rå verktygsoutput — använd den som underlag."
    )
    return "VERKTYG (använd när relevant — inte valfritt att hoppa över):\n" + "\n".join(
        lines
    )


def apply_population_agent_tools(
    agent_graph: Any,
    population_indices: set[int],
    options: OasisRunOptions,
) -> None:
    """Attach search/SymPy toolkits to population agents after graph generation."""
    extra_tools = build_population_extra_tools(options)
    if not extra_tools:
        return
    max_iteration = population_agent_max_iteration(options)
    for agent_id, agent in agent_graph.get_agents():
        if agent_id not in population_indices:
            continue
        agent.add_tools(extra_tools)
        agent.max_iteration = max_iteration
