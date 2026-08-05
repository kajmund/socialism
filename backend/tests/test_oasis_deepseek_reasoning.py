"""Tests for DeepSeek reasoning_content preservation patch."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import app.services.oasis_deepseek_reasoning as reasoning_mod
from app.services.oasis_deepseek_reasoning import (
    _attach_reasoning,
    _extract_reasoning_content,
    apply_deepseek_reasoning_patch,
)


def test_extract_reasoning_content_from_attribute():
    msg = SimpleNamespace(reasoning_content="chain of thought")
    assert _extract_reasoning_content(msg) == "chain of thought"


def test_extract_reasoning_content_from_model_dump():
    msg = SimpleNamespace(
        reasoning_content=None,
        model_dump=lambda exclude_none=True: {"reasoning_content": "dumped"},
    )
    assert _extract_reasoning_content(msg) == "dumped"


def test_attach_reasoning_to_assistant_message():
    out = _attach_reasoning(
        {"role": "assistant", "content": "", "tool_calls": []},
        {"reasoning_content": "keep me"},
    )
    assert out["reasoning_content"] == "keep me"


def test_apply_patch_records_reasoning_on_tool_call_message():
    reasoning_mod._PATCHED = False
    apply_deepseek_reasoning_patch()

    from camel.agents.chat_agent import ChatAgent
    from camel.messages.func_message import FunctionCallingMessage
    from camel.types import OpenAIBackendRole, RoleType

    agent = ChatAgent.__new__(ChatAgent)
    agent.role_name = "Assistant"
    agent.role_type = RoleType.ASSISTANT
    agent._deepseek_pending_reasoning = "reasoning chain"
    agent.update_memory = MagicMock()

    record = ChatAgent._record_tool_calling(
        agent,
        "search_duckduckgo",
        {"query": "test"},
        "result text",
        "call_123",
    )

    assert record.tool_name == "search_duckduckgo"
    assist_call = agent.update_memory.call_args_list[0]
    assist_msg = assist_call.args[0]
    assert isinstance(assist_msg, FunctionCallingMessage)
    assert assist_msg.meta_dict == {"reasoning_content": "reasoning chain"}
    openai_msg = assist_msg.to_openai_assistant_message()
    assert openai_msg["reasoning_content"] == "reasoning chain"
    assert assist_call.args[1] == OpenAIBackendRole.ASSISTANT


def test_handle_batch_response_wrapper_stores_pending_reasoning():
    reasoning_mod._PATCHED = False
    apply_deepseek_reasoning_patch()

    from camel.agents.chat_agent import ChatAgent

    agent = ChatAgent.__new__(ChatAgent)
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(reasoning_content="from api"),
            )
        ]
    )

    reasoning_mod._ORIG_HANDLE_BATCH = MagicMock(return_value=MagicMock())
    ChatAgent._handle_batch_response(agent, response)
    assert agent._deepseek_pending_reasoning == "from api"
