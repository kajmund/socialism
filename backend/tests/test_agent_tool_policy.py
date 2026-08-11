"""Tests for CAMEL SocialAgent tool policy during OASIS runs."""

from app.services.simulation.agent_tool_policy import CamelCommentToolPolicy


class _MockGraph:
    def __init__(self, agents: dict[int, object]) -> None:
        self._agents = agents

    def get_agent(self, agent_id: int) -> object:
        return self._agents[agent_id]


class _MockAgent:
    def __init__(self, *, with_comment_tool: bool = True) -> None:
        self._internal_tools: dict[str, str] = {}
        if with_comment_tool:
            self._internal_tools["create_comment"] = "comment_tool"
        self.add_tool_calls = 0
        self.remove_tool_calls = 0

    def add_tool(self, tool: object) -> None:
        self.add_tool_calls += 1
        self._internal_tools["create_comment"] = tool  # type: ignore[assignment]

    def remove_tool(self, name: str) -> None:
        self.remove_tool_calls += 1
        del self._internal_tools[name]


def test_register_captures_comment_tools():
    agent = _MockAgent()
    graph = _MockGraph({2: agent})
    policy = CamelCommentToolPolicy()
    policy.register_population_agents(graph, {2})
    policy.set_comment_allowed(agent, 2, allowed=False)
    assert "create_comment" not in agent._internal_tools
    assert agent.remove_tool_calls == 1


def test_set_comment_allowed_restores_stored_tool():
    agent = _MockAgent()
    graph = _MockGraph({1: agent})
    policy = CamelCommentToolPolicy()
    policy.register_population_agents(graph, {1})
    policy.set_comment_allowed(agent, 1, allowed=False)
    policy.set_comment_allowed(agent, 1, allowed=True)
    assert agent._internal_tools["create_comment"] == "comment_tool"
    assert agent.add_tool_calls == 1


def test_set_comment_allowed_noop_when_disallowed_and_absent():
    agent = _MockAgent(with_comment_tool=False)
    policy = CamelCommentToolPolicy()
    policy.set_comment_allowed(agent, 5, allowed=False)
    assert agent.remove_tool_calls == 0
