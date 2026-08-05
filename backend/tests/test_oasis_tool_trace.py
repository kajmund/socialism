"""Tests for OASIS external tool trace collection."""

from unittest.mock import MagicMock

import app.services.oasis_tool_trace as trace_mod
from app.services.oasis_tool_trace import (
    apply_oasis_tool_trace_patch,
    clear_oasis_tool_trace,
    drain_oasis_tool_trace,
    is_external_tool,
    set_oasis_tool_trace_tick,
)


def setup_function():
    trace_mod._PATCHED = False
    clear_oasis_tool_trace()


def test_is_external_tool():
    assert is_external_tool("search_duckduckgo") is True
    assert is_external_tool("simplify_expression") is True
    assert is_external_tool("like_post") is False
    assert is_external_tool("CREATE_POST") is False


def test_tool_trace_records_external_tools_only():
    trace_mod._PATCHED = False
    apply_oasis_tool_trace_patch()

    from camel.agents.chat_agent import ChatAgent

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
