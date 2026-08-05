"""Preserve DeepSeek thinking-mode reasoning_content through CAMEL tool loops.

DeepSeek requires assistant messages that performed tool calls to include
reasoning_content on every subsequent API request. CAMEL drops the field when
recording FunctionCallingMessage — patch at runtime before OASIS runs.
"""

from __future__ import annotations

import time
from typing import Any

_PATCHED = False
_ORIG_HANDLE_BATCH = None
_ORIG_BASE_ASSISTANT = None
_ORIG_FUNC_ASSISTANT = None


def _extract_reasoning_content(message: Any) -> str | None:
    reasoning = getattr(message, "reasoning_content", None)
    if isinstance(reasoning, str) and reasoning:
        return reasoning
    model_dump = getattr(message, "model_dump", None)
    if callable(model_dump):
        data = model_dump(exclude_none=True)
        if isinstance(data, dict):
            value = data.get("reasoning_content")
            if isinstance(value, str) and value:
                return value
    return None


def _attach_reasoning(
    message_dict: dict[str, Any], meta_dict: dict[str, Any] | None
) -> dict[str, Any]:
    if not meta_dict:
        return message_dict
    reasoning = meta_dict.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        message_dict = dict(message_dict)
        message_dict["reasoning_content"] = reasoning
    return message_dict


def apply_deepseek_reasoning_patch() -> None:
    """Monkeypatch CAMEL so DeepSeek thinking-mode tool loops keep reasoning_content."""
    global _PATCHED, _ORIG_HANDLE_BATCH, _ORIG_BASE_ASSISTANT, _ORIG_FUNC_ASSISTANT
    if _PATCHED:
        return

    from camel.agents.chat_agent import ChatAgent
    from camel.messages.base import BaseMessage
    from camel.messages.func_message import FunctionCallingMessage
    from camel.types import OpenAIBackendRole
    from camel.types.agents import ToolCallingRecord

    _ORIG_HANDLE_BATCH = ChatAgent._handle_batch_response
    _ORIG_BASE_ASSISTANT = BaseMessage.to_openai_assistant_message
    _ORIG_FUNC_ASSISTANT = FunctionCallingMessage.to_openai_assistant_message

    def handle_batch_response(self, response):
        result = _ORIG_HANDLE_BATCH(self, response)
        reasoning: str | None = None
        choices = getattr(response, "choices", None) or []
        if choices:
            reasoning = _extract_reasoning_content(choices[0].message)
        self._deepseek_pending_reasoning = reasoning
        return result

    def record_tool_calling(
        self,
        func_name: str,
        args: dict[str, Any],
        result: Any,
        tool_call_id: str,
        mask_output: bool = False,
    ):
        meta_dict: dict[str, Any] | None = None
        reasoning = getattr(self, "_deepseek_pending_reasoning", None)
        if isinstance(reasoning, str) and reasoning:
            meta_dict = {"reasoning_content": reasoning}

        assist_msg = FunctionCallingMessage(
            role_name=self.role_name,
            role_type=self.role_type,
            meta_dict=meta_dict,
            content="",
            func_name=func_name,
            args=args,
            tool_call_id=tool_call_id,
        )
        func_msg = FunctionCallingMessage(
            role_name=self.role_name,
            role_type=self.role_type,
            meta_dict=None,
            content="",
            func_name=func_name,
            result=result,
            tool_call_id=tool_call_id,
            mask_output=mask_output,
        )

        current_time_ns = time.time_ns()
        base_timestamp = current_time_ns / 1_000_000_000

        self.update_memory(
            assist_msg, OpenAIBackendRole.ASSISTANT, timestamp=base_timestamp
        )
        self.update_memory(
            func_msg,
            OpenAIBackendRole.FUNCTION,
            timestamp=base_timestamp + 1e-6,
        )

        return ToolCallingRecord(
            tool_name=func_name,
            args=args,
            result=result,
            tool_call_id=tool_call_id,
        )

    def base_to_openai_assistant_message(self):
        return _attach_reasoning(
            _ORIG_BASE_ASSISTANT(self),
            self.meta_dict,
        )

    def func_to_openai_assistant_message(self):
        return _attach_reasoning(
            _ORIG_FUNC_ASSISTANT(self),
            self.meta_dict,
        )

    ChatAgent._handle_batch_response = handle_batch_response
    ChatAgent._record_tool_calling = record_tool_calling
    BaseMessage.to_openai_assistant_message = base_to_openai_assistant_message
    FunctionCallingMessage.to_openai_assistant_message = func_to_openai_assistant_message
    _PATCHED = True
