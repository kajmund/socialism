"""Non-mutating observation at the production workspace-handler boundary."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.services.workspace.tool_handlers import HANDLERS
from scripts.document_presentation_benchmark.step_b_types import HandlerCapture

_active_capture: ContextVar[HandlerCapture | None] = ContextVar(
    "step_b_find_capture",
    default=None,
)


@contextmanager
def install_find_capture():
    original = HANDLERS["find_documents"]

    async def observed(context, arguments: dict[str, Any]) -> dict[str, Any]:
        capture = _active_capture.get()
        if capture is not None:
            capture.arguments.append(dict(arguments))
        result = await original(context, arguments)
        if capture is not None:
            capture.results.append(dict(result))
        return result

    HANDLERS["find_documents"] = observed
    try:
        yield
    finally:
        HANDLERS["find_documents"] = original


@contextmanager
def capture_find_calls(capture: HandlerCapture):
    token = _active_capture.set(capture)
    try:
        yield
    finally:
        _active_capture.reset(token)

