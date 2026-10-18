"""Production delivery-adapter wrappers used by the three benchmark channels."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.api.sme_ws import _send_workspace_tools
from app.services.live_speech_runtime import LiveSpeechRuntime
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime
from scripts.document_presentation_benchmark.step_b_types import (
    Channel,
    DeliveryCapture,
)

ClientTools = Callable[[list[dict[str, Any]]], Awaitable[None]]


def delivery_adapter(
    channel: Channel,
    capture: DeliveryCapture,
    *,
    request_id: str,
    persona_id: str,
) -> ClientTools:
    if channel == "text":
        return _text_adapter(capture, request_id=request_id, persona_id=persona_id)
    if channel == "voice":
        return _voice_adapter(capture, request_id=request_id)
    if channel == "group_voice":
        return _group_adapter(capture, persona_id=persona_id)
    raise AssertionError(f"unhandled channel: {channel}")


def _text_adapter(
    capture: DeliveryCapture,
    *,
    request_id: str,
    persona_id: str,
) -> ClientTools:
    envelope = {
        "thread_type": "expert",
        "thread_id": persona_id,
        "request_id": request_id,
    }
    capture.envelope = {"adapter": "_send_workspace_tools", **envelope}

    async def emit(payload: dict[str, Any]) -> None:
        capture.events.append(payload)

    async def deliver(calls: list[dict[str, Any]]) -> None:
        await _send_workspace_tools(emit, envelope, calls)

    return deliver


def _voice_adapter(capture: DeliveryCapture, *, request_id: str) -> ClientTools:
    turn_id = f"fixed-transcript-{request_id}"
    capture.envelope = {
        "adapter": "LiveSpeechRuntime._client_tools",
        "turn_id": turn_id,
        "transcript": "fixed",
    }
    runtime = object.__new__(LiveSpeechRuntime)

    async def emit(payload: dict[str, Any]) -> None:
        capture.events.append(payload)

    runtime._emit_json = emit
    return runtime._client_tools(turn_id)


def _group_adapter(
    capture: DeliveryCapture,
    *,
    persona_id: str,
) -> ClientTools:
    session = GroupVoiceSession(
        panel_id=f"step-b-{persona_id}",
        member_ids={persona_id},
        member_names={persona_id: "Benchmarkjuristen"},
        floor=persona_id,
        floor_reason="name",
    )
    capture.envelope = {
        "adapter": "GroupVoiceAudioRuntime.emit_workspace_tool",
        "floor_owner": session.floor,
        "floor_owned_by_expert": session.floor == persona_id,
    }
    runtime = object.__new__(GroupVoiceAudioRuntime)
    runtime.session = session

    async def emit(payload: dict[str, Any]) -> None:
        capture.events.append(payload)

    runtime._emit_json = emit

    async def deliver(calls: list[dict[str, Any]]) -> None:
        await runtime.emit_workspace_tool(calls, expert_id=persona_id)

    return deliver

