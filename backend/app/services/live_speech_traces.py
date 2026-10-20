"""Forward in-character model traces onto the live-speech socket."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.services.live_speech_scope import LiveSpeechScope

EmitJson = Callable[[dict], Awaitable[None]]


async def forward_library_trace(
    scope: LiveSpeechScope,
    payload: dict,
    emit_json: EmitJson,
) -> None:
    if payload.get("type") != "model_trace":
        return
    if payload.get("thread_id") != scope.expert_id:
        return
    workspace_id = payload.get("workspace_id")
    if workspace_id not in (None, scope.workspace_id):
        return
    target = payload.get("target_user_id")
    if target not in (None, scope.user_id):
        return
    await emit_json(payload)
