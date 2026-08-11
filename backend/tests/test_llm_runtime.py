"""Tests for unified CAMEL LLM runtime (DeepSeek + tool trace)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.oasis_tool_trace import clear_oasis_tool_trace, drain_oasis_tool_trace
from app.services.simulation.llm_runtime import (
    _attach_reasoning,
    _extract_reasoning_content,
    camel_llm_runtime,
    runtime_depth,
)


def test_extract_reasoning_content_from_attribute():
    msg = SimpleNamespace(reasoning_content="chain of thought")
    assert _extract_reasoning_content(msg) == "chain of thought"


def test_attach_reasoning_to_assistant_message():
    out = _attach_reasoning(
        {"role": "assistant", "content": "", "tool_calls": []},
        {"reasoning_content": "keep me"},
    )
    assert out["reasoning_content"] == "keep me"


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
    try:
        from camel.agents.chat_agent import ChatAgent
        from camel.messages.base import BaseMessage
        from camel.messages.func_message import FunctionCallingMessage

        if rt._SAVED:
            ChatAgent._handle_batch_response = rt._SAVED["handle_batch_response"]
            ChatAgent._record_tool_calling = rt._SAVED["record_tool_calling"]
            BaseMessage.to_openai_assistant_message = rt._SAVED["base_assistant"]
            FunctionCallingMessage.to_openai_assistant_message = rt._SAVED[
                "func_assistant"
            ]
    except ImportError:
        pass


def test_runtime_restores_chat_agent_after_exit(camel_available):
    from camel.agents.chat_agent import ChatAgent

    original_record = ChatAgent._record_tool_calling
    with camel_llm_runtime():
        assert ChatAgent._record_tool_calling is not original_record
        assert runtime_depth() == 1
    assert ChatAgent._record_tool_calling is original_record
    assert runtime_depth() == 0


def test_runtime_refcount_holds_patch_until_last_exit(camel_available):
    from camel.agents.chat_agent import ChatAgent

    original_record = ChatAgent._record_tool_calling
    with camel_llm_runtime():
        patched = ChatAgent._record_tool_calling
        with camel_llm_runtime():
            assert ChatAgent._record_tool_calling is patched
            assert runtime_depth() == 2
        assert ChatAgent._record_tool_calling is patched
        assert runtime_depth() == 1
    assert ChatAgent._record_tool_calling is original_record


def test_record_tool_calling_preserves_reasoning_and_traces_external_tools(
    camel_available,
):
    import app.services.simulation.llm_runtime as rt
    from camel.agents.chat_agent import ChatAgent
    from camel.messages.func_message import FunctionCallingMessage
    from camel.types import OpenAIBackendRole, RoleType

    clear_oasis_tool_trace()
    with camel_llm_runtime():
        agent = ChatAgent.__new__(ChatAgent)
        agent.role_name = "Assistant"
        agent.role_type = RoleType.ASSISTANT
        agent.social_agent_id = 3
        agent._deepseek_pending_reasoning = "reasoning chain"
        agent.update_memory = MagicMock()

        social = ChatAgent._record_tool_calling(
            agent,
            "like_post",
            {"post_id": 1},
            "ok",
            "call_social",
        )
        assert social.tool_name == "like_post"
        assert drain_oasis_tool_trace() == []

        external = ChatAgent._record_tool_calling(
            agent,
            "search_wiki",
            {"entity": "Sverige"},
            "Sweden…",
            "call_ext",
        )
        assert external.tool_name == "search_wiki"
        trace = drain_oasis_tool_trace()
        assert len(trace) == 1
        assert trace[0]["tool_name"] == "search_wiki"
        assert trace[0]["user_id"] == 3

        assist_msg = agent.update_memory.call_args_list[0].args[0]
        assert isinstance(assist_msg, FunctionCallingMessage)
        assert assist_msg.meta_dict == {"reasoning_content": "reasoning chain"}
        assert assist_msg.to_openai_assistant_message()["reasoning_content"] == (
            "reasoning chain"
        )
        assert agent.update_memory.call_args_list[0].args[1] == OpenAIBackendRole.ASSISTANT


def test_handle_batch_response_stores_pending_reasoning(camel_available):
    import app.services.simulation.llm_runtime as rt
    from camel.agents.chat_agent import ChatAgent

    with camel_llm_runtime():
        rt._SAVED["handle_batch_response"] = MagicMock(return_value=MagicMock())
        agent = ChatAgent.__new__(ChatAgent)
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(reasoning_content="from api"),
                )
            ]
        )
        ChatAgent._handle_batch_response(agent, response)
        assert agent._deepseek_pending_reasoning == "from api"
