"""Runtime tool policy for CAMEL SocialAgent instances during OASIS simulations.

Encapsulates access to SocialAgent._internal_tools so the tick loop does not
depend on CAMEL class internals directly.
"""

from __future__ import annotations

from typing import Any


class CamelCommentToolPolicy:
    """Enable or disable create_comment per agent based on engagement rules."""

    def __init__(self) -> None:
        self._stored_tools: dict[int, Any] = {}

    def register_population_agents(
        self, agent_graph: Any, population_indices: set[int]
    ) -> None:
        """Capture each population agent's create_comment tool for later restore."""
        for agent_id in population_indices:
            agent = agent_graph.get_agent(agent_id)
            internal_tools = getattr(agent, "_internal_tools", {})
            tool = internal_tools.get("create_comment")
            if tool is not None:
                self._stored_tools[agent_id] = tool

    def set_comment_allowed(
        self, agent: Any, agent_id: int, *, allowed: bool
    ) -> None:
        """Gate create_comment on one agent before an LLMAction round."""
        stored_tool = self._stored_tools.get(agent_id)
        internal_tools = getattr(agent, "_internal_tools", {})
        has_comment = "create_comment" in internal_tools
        if allowed:
            if not has_comment and stored_tool is not None:
                agent.add_tool(stored_tool)
        elif has_comment:
            agent.remove_tool("create_comment")
