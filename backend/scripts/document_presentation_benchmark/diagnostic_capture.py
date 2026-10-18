"""Capture routing and model boundaries without changing expert behavior."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from app.services import expert_async_tools, expert_reasoning_episode
from app.services import expert_reasoning_turn


@dataclass
class DiagnosticCapture:
    events: list[dict[str, Any]] = field(default_factory=list)


_active: ContextVar[DiagnosticCapture | None] = ContextVar(
    "document_channel_diagnostic",
    default=None,
)


@contextmanager
def install_diagnostic_capture():
    initial_complete = expert_async_tools.complete_with_tools
    continuation_complete = expert_reasoning_episode.complete_with_tools
    expose = expert_reasoning_turn.expose_workspace_tools
    exposure = expert_reasoning_turn.exposure_for_scores
    run_workspace_tool = expert_async_tools.run_workspace_tool_call

    async def traced_initial(messages, specs, **kwargs):
        return await _trace_completion(
            "initial_model",
            initial_complete,
            messages=messages,
            specs=specs,
            kwargs=kwargs,
        )

    async def traced_continuation(messages, specs, **kwargs):
        return await _trace_completion(
            "continuation_model",
            continuation_complete,
            messages=messages,
            specs=specs,
            kwargs=kwargs,
        )

    async def traced_expose(**kwargs):
        try:
            exposed, record = await expose(**kwargs)
        except Exception as exc:
            _append(
                {
                    "stage": "post_result_route"
                    if kwargs.get("reroute")
                    else "initial_route",
                    "error": _error(exc),
                }
            )
            raise
        _append(
            {
                "stage": "post_result_route"
                if kwargs.get("reroute")
                else "initial_route",
                "offered": _spec_names(kwargs["specs"]),
                "exposed": _spec_names(exposed),
                "ranking": list(record.ranking),
                "scores": record.scores,
                "require_tool": record.require_tool,
                "fallback": record.fallback,
                "error_category": record.error_category,
                "tool_result_present": bool(kwargs.get("tool_result")),
            }
        )
        return exposed, record

    def traced_exposure(*args, **kwargs):
        specs = kwargs.get("specs", args[1] if len(args) > 1 else ())
        try:
            exposed, record = exposure(*args, **kwargs)
        except Exception as exc:
            _append({"stage": "initial_route", "error": _error(exc)})
            raise
        _append(
            {
                "stage": "initial_route",
                "offered": _spec_names(specs),
                "exposed": _spec_names(exposed),
                "ranking": list(record.ranking),
                "scores": record.scores,
                "require_tool": record.require_tool,
                "fallback": record.fallback,
                "error_category": record.error_category,
                "tool_result_present": False,
            }
        )
        return exposed, record

    async def traced_workspace_tool(call, work):
        event = {
            "stage": "workspace_tool_execution",
            "name": call.name,
            "arguments": call.arguments,
        }
        try:
            result = await run_workspace_tool(call, work)
        except Exception as exc:
            event["error"] = _error(exc)
            _append(event)
            raise
        event["result"] = result[:1000]
        _append(event)
        return result

    with (
        patch.object(expert_async_tools, "complete_with_tools", traced_initial),
        patch.object(
            expert_reasoning_episode,
            "complete_with_tools",
            traced_continuation,
        ),
        patch.object(expert_reasoning_turn, "expose_workspace_tools", traced_expose),
        patch.object(expert_reasoning_turn, "exposure_for_scores", traced_exposure),
        patch.object(
            expert_async_tools,
            "run_workspace_tool_call",
            traced_workspace_tool,
        ),
    ):
        yield


@contextmanager
def capture_diagnostics(capture: DiagnosticCapture):
    token = _active.set(capture)
    try:
        yield
    finally:
        _active.reset(token)


async def _trace_completion(stage, complete, *, messages, specs, kwargs):
    event = {
        "stage": stage,
        "offered": _spec_names(specs),
        "tool_choice": kwargs.get("tool_choice", "auto"),
    }
    try:
        reply = await complete(messages, specs, **kwargs)
    except Exception as exc:
        event["error"] = _error(exc)
        _append(event)
        raise
    event["tool_calls"] = _reply_calls(reply)
    event["has_text"] = bool(str(getattr(reply, "content", "") or "").strip())
    _append(event)
    return reply


def _reply_calls(reply: object) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for call in list(getattr(reply, "tool_calls", None) or []):
        function = getattr(call, "function", None)
        calls.append(
            {
                "id": str(getattr(call, "id", "") or ""),
                "name": str(getattr(function, "name", "") or ""),
                "arguments": str(getattr(function, "arguments", "") or ""),
            }
        )
    return calls


def _spec_names(specs) -> list[str]:
    return [
        str(spec.get("function", {}).get("name") or "")
        for spec in specs
        if isinstance(spec, dict)
    ]


def _append(event: dict[str, Any]) -> None:
    capture = _active.get()
    if capture is not None:
        capture.events.append(event)


def _error(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)[:500]}
