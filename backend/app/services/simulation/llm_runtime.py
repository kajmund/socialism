"""Unified CAMEL LLM runtime patches for OASIS simulations.

Combines DeepSeek reasoning_content preservation and external-tool trace
collection in one _record_tool_calling implementation. Patches are applied
via camel_llm_runtime() with reference counting so concurrent A/B variants
share patched classes safely and originals restore when the last run exits.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from collections.abc import Generator
from typing import Any

from app.services.oasis_tool_trace import (
    _agent_index,
    _preview,
    _safe_args,
    is_external_tool,
)

_RUNTIME_DEPTH = 0
_SAVED: dict[str, Any] = {}


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


def _int_id(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ids_from_mapping(data: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("post_id", "comment_id", "like_id"):
        parsed = _int_id(data.get(key))
        if parsed is not None:
            out[key] = parsed
    return out


def _ids_from_result(result: Any) -> dict[str, int]:
    if isinstance(result, dict):
        return _ids_from_mapping(result)
    if isinstance(result, str):
        text = result.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                return _ids_from_mapping(parsed)
    return {}


def _append_external_tool_trace(
    agent: Any,
    func_name: str,
    args: dict[str, Any],
    result: Any,
) -> None:
    from app.services.oasis_tool_trace import _SEQUENCE, _TICK_INDEX, _TRACE

    trace = _TRACE.get()
    if trace is None:
        return

    seq = _SEQUENCE.get() + 1
    _SEQUENCE.set(seq)
    agent_index = _agent_index(agent)
    trace.append(
        {
            "user_id": agent_index if agent_index is not None else -1,
            "tick_index": _TICK_INDEX.get(),
            "sequence": seq,
            "tool_name": func_name,
            "args": _safe_args(args),
            "result_preview": _preview(result),
        }
    )


def _append_reasoning_trace(
    agent: Any,
    func_name: str,
    args: dict[str, Any],
    result: Any,
    reasoning: str,
) -> None:
    from app.services.oasis_tool_trace import _REASONING_TRACE, _TICK_INDEX

    trace = _REASONING_TRACE.get()
    if trace is None:
        return

    agent_index = _agent_index(agent)
    row: dict[str, Any] = {
        "tick_index": _TICK_INDEX.get(),
        "user_id": agent_index if agent_index is not None else -1,
        "func_name": func_name,
        "reasoning_content": _preview(reasoning, limit=2000) or reasoning,
    }
    post_id = _int_id(args.get("post_id"))
    if post_id is not None:
        row["post_id"] = post_id
    for key, value in _ids_from_result(result).items():
        row[key] = value
    trace.append(row)


def _apply_llm_patches() -> None:
    from camel.agents.chat_agent import ChatAgent
    from camel.messages.base import BaseMessage
    from camel.messages.func_message import FunctionCallingMessage
    from camel.types import OpenAIBackendRole
    from camel.types.agents import ToolCallingRecord

    _SAVED["handle_batch_response"] = ChatAgent._handle_batch_response
    _SAVED["record_tool_calling"] = ChatAgent._record_tool_calling
    _SAVED["base_assistant"] = BaseMessage.to_openai_assistant_message
    _SAVED["func_assistant"] = FunctionCallingMessage.to_openai_assistant_message

    def handle_batch_response(self, response):
        result = _SAVED["handle_batch_response"](self, response)
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

        record = ToolCallingRecord(
            tool_name=func_name,
            args=args,
            result=result,
            tool_call_id=tool_call_id,
        )

        if is_external_tool(func_name):
            _append_external_tool_trace(self, func_name, args, result)

        if isinstance(reasoning, str) and reasoning:
            _append_reasoning_trace(self, func_name, args, result, reasoning)

        return record

    def base_to_openai_assistant_message(self):
        return _attach_reasoning(
            _SAVED["base_assistant"](self),
            self.meta_dict,
        )

    def func_to_openai_assistant_message(self):
        return _attach_reasoning(
            _SAVED["func_assistant"](self),
            self.meta_dict,
        )

    ChatAgent._handle_batch_response = handle_batch_response
    ChatAgent._record_tool_calling = record_tool_calling
    BaseMessage.to_openai_assistant_message = base_to_openai_assistant_message
    FunctionCallingMessage.to_openai_assistant_message = func_to_openai_assistant_message


def _restore_llm_patches() -> None:
    if not _SAVED:
        return

    from camel.agents.chat_agent import ChatAgent
    from camel.messages.base import BaseMessage
    from camel.messages.func_message import FunctionCallingMessage

    ChatAgent._handle_batch_response = _SAVED["handle_batch_response"]
    ChatAgent._record_tool_calling = _SAVED["record_tool_calling"]
    BaseMessage.to_openai_assistant_message = _SAVED["base_assistant"]
    FunctionCallingMessage.to_openai_assistant_message = _SAVED["func_assistant"]
    _SAVED.clear()


def _enter_llm_runtime() -> None:
    global _RUNTIME_DEPTH
    if _RUNTIME_DEPTH == 0:
        _apply_llm_patches()
    _RUNTIME_DEPTH += 1


def _exit_llm_runtime() -> None:
    global _RUNTIME_DEPTH
    _RUNTIME_DEPTH -= 1
    if _RUNTIME_DEPTH <= 0:
        _RUNTIME_DEPTH = 0
        _restore_llm_patches()


@contextmanager
def camel_llm_runtime() -> Generator[None, None, None]:
    """Apply CAMEL LLM patches for one OASIS run; restore when the last scope exits."""
    _enter_llm_runtime()
    try:
        yield
    finally:
        _exit_llm_runtime()


def runtime_depth() -> int:
    """Active camel_llm_runtime scopes (for tests)."""
    return _RUNTIME_DEPTH
