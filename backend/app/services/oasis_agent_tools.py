"""Optional CAMEL toolkits for OASIS population agents (search, SymPy)."""

from __future__ import annotations

from typing import Any

from app.schemas.domain import OasisRunOptions

# OASIS cookbook examples use max_iteration=5 when agents have external tools.
_TOOL_MAX_ITERATION = 5


def population_agent_max_iteration(options: OasisRunOptions) -> int:
    if options.enable_web_search or options.enable_sympy_tools:
        return _TOOL_MAX_ITERATION
    return 1


def build_population_extra_tools(options: OasisRunOptions) -> list[Any]:
    """Return CAMEL tools to attach to population agents (empty if all disabled)."""
    tools: list[Any] = []
    if options.enable_web_search:
        from camel.toolkits import SearchToolkit

        search = SearchToolkit()
        tools.append(search.search_duckduckgo)
        tools.append(search.search_wiki)
    if options.enable_sympy_tools:
        from camel.toolkits import SymPyToolkit

        tools.extend(SymPyToolkit().get_tools())
    return tools


def population_tool_rules(options: OasisRunOptions) -> str:
    """Swedish guidance appended to population user_char when tools are enabled."""
    if not options.enable_web_search and not options.enable_sympy_tools:
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
    if options.enable_web_search:
        lines.append(
            "- Webb/Wikipedia: search_wiki för bakgrund om begrepp, institutioner "
            "eller aktörer; search_duckduckgo för aktuella nyheter och siffror. "
            "Sök på det konkreta (t.ex. plats, lag, belopp) — inte bara "
            "partinamnet."
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
