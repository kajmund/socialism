"""Tests for OASIS external tool trace collection."""

from unittest.mock import MagicMock

import pytest

import app.services.oasis_tool_trace as trace_mod
from app.services.oasis_tool_trace import (
    clear_oasis_tool_trace,
    drain_oasis_reasoning_trace,
    drain_oasis_tool_trace,
    is_external_tool,
    set_oasis_tool_trace_tick,
)
from app.services.simulation.llm_runtime import camel_llm_runtime


def setup_function():
    clear_oasis_tool_trace()


def test_is_external_tool():
    assert is_external_tool("search_duckduckgo") is True
    assert is_external_tool("simplify_expression") is True
    assert is_external_tool("like_post") is False
    assert is_external_tool("CREATE_POST") is False


@pytest.fixture
def camel_available():
    try:
        from camel.agents.chat_agent import ChatAgent  # noqa: F401
    except ImportError:
        pytest.skip("camel-oasis not installed")
    import app.services.simulation.llm_runtime as rt

    rt._RUNTIME_DEPTH = 0
    rt._SAVED.clear()
    yield
    rt._RUNTIME_DEPTH = 0
    rt._SAVED.clear()


def test_tool_trace_records_external_tools_only(camel_available):
    from camel.agents.chat_agent import ChatAgent

    with camel_llm_runtime():
        agent = MagicMock()
        agent.social_agent_id = 3

        set_oasis_tool_trace_tick(2)
        ChatAgent._record_tool_calling(
            agent,
            "search_wiki",
            {"entity": "Sverige"},
            "Sweden is a country…",
            "call_1",
        )
        ChatAgent._record_tool_calling(
            agent,
            "like_post",
            {"post_id": 1},
            "ok",
            "call_2",
        )

        rows = drain_oasis_tool_trace()
        assert len(rows) == 1
        assert rows[0]["user_id"] == 3
        assert rows[0]["tick_index"] == 2
        assert rows[0]["tool_name"] == "search_wiki"
        assert rows[0]["args"] == {"entity": "Sverige"}


def test_tool_trace_is_task_local():
    """Parallel variants must not share one process-global buffer."""
    clear_oasis_tool_trace()
    set_oasis_tool_trace_tick(0)
    from contextvars import copy_context

    def other_variant() -> list:
        clear_oasis_tool_trace()
        set_oasis_tool_trace_tick(1)
        trace = trace_mod._TRACE.get()
        assert trace is not None
        trace.append({"user_id": 9, "tick_index": 1, "tool_name": "search_wiki"})
        return drain_oasis_tool_trace()

    ctx = copy_context()
    other_rows = ctx.run(other_variant)
    assert len(other_rows) == 1
    assert other_rows[0]["user_id"] == 9
    assert drain_oasis_tool_trace() == []


def test_reasoning_trace_links_post_id_from_args_and_result(camel_available):
    from camel.agents.chat_agent import ChatAgent
    from camel.types import RoleType

    with camel_llm_runtime():
        agent = ChatAgent.__new__(ChatAgent)
        agent.role_name = "Assistant"
        agent.role_type = RoleType.ASSISTANT
        agent.social_agent_id = 5
        agent._deepseek_pending_reasoning = "Jag vill svara på det här inlägget."
        agent.update_memory = MagicMock()

        set_oasis_tool_trace_tick(1)
        ChatAgent._record_tool_calling(
            agent,
            "create_comment",
            {"post_id": 42, "content": "Bra poäng."},
            {"comment_id": 123},
            "call_comment",
        )

        rows = drain_oasis_reasoning_trace()
        assert len(rows) == 1
        assert rows[0]["user_id"] == 5
        assert rows[0]["tick_index"] == 1
        assert rows[0]["func_name"] == "create_comment"
        assert rows[0]["post_id"] == 42
        assert rows[0]["comment_id"] == 123
        assert "Jag vill svara" in rows[0]["reasoning_content"]
        assert drain_oasis_tool_trace() == []


def test_append_reasoning_trace_without_camel():
    from app.services.simulation.llm_runtime import _append_reasoning_trace

    clear_oasis_tool_trace()
    set_oasis_tool_trace_tick(2)
    agent = MagicMock()
    agent.social_agent_id = 7

    _append_reasoning_trace(
        agent,
        "create_comment",
        {"post_id": 42, "content": "Hej"},
        {"comment_id": 99},
        "Resonemang om kommentaren.",
    )

    rows = drain_oasis_reasoning_trace()
    assert len(rows) == 1
    assert rows[0]["user_id"] == 7
    assert rows[0]["tick_index"] == 2
    assert rows[0]["func_name"] == "create_comment"
    assert rows[0]["post_id"] == 42
    assert rows[0]["comment_id"] == 99
    assert rows[0]["reasoning_content"] == "Resonemang om kommentaren."
