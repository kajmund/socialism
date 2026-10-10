"""WebSocket for SME panel (group) live voice sessions — phase 1.

Uses GroupVoiceSession for floor / hands / Jev keep-lower / shared tool results
and GroupVoiceAudioRuntime for STT + floor-driven TTS.

All experts in the panel must be configured with the "socialism" live-voice
provider. Each expert speaks with the voice stored on their persona
(live_voice).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.auth.tokens import user_from_bearer_token
from app.config import settings
from app.database.models import Kund, Population, PopulationMember, UserAccount
from app.services import jobs as jobs_service
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_runtime import (
    GroupVoiceAudioRuntime,
    GroupVoiceAudioScope,
)
from app.services.sme_group_voice_turns import run_floor_turn
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class StartSession(BaseModel):
    type: str = "start"
    panel_id: str = Field(min_length=1)
    language: str = "sv"


class HumanUtterance(BaseModel):
    type: str = "utterance"
    text: str = Field(max_length=10_000)


class RaiseHand(BaseModel):
    type: str = "raise_hand"
    persona_id: str


class GrantFloor(BaseModel):
    type: str = "grant_floor"
    persona_id: str


class ReleaseFloor(BaseModel):
    type: str = "release_floor"
    transcript: str = ""


class AttachTool(BaseModel):
    type: str = "attach_tool"
    persona_id: str
    tool_name: str
    summary: str = ""
    result: Any = None


class SpeakAs(BaseModel):
    type: str = "speak_as"
    persona_id: str
    text: str = Field(max_length=10_000)


async def _authenticate(websocket: WebSocket) -> UserAccount:
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        return await user_from_bearer_token(
            session,
            websocket.query_params.get("access_token"),
        )


async def _load_panel_session(
    panel_id: str,
    user: UserAccount,
) -> tuple[GroupVoiceSession, dict[str, str]]:
    if user.kund_id is None:
        raise HTTPException(status_code=403, detail="kund_access_denied")
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        kund = await session.get(Kund, user.kund_id)
        if kund is None or kund.product != "sme":
            raise HTTPException(status_code=403, detail="sme_product_required")
        try:
            pid = int(panel_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="panel_not_found") from exc
        result = await session.execute(
            select(Population)
            .where(
                Population.id == pid,
                Population.customer_id == user.kund_id,
                Population.kind == "expert_panel",
            )
            .options(selectinload(Population.members).selectinload(PopulationMember.persona))
        )
        panel = result.scalar_one_or_none()
        if panel is None:
            raise HTTPException(status_code=404, detail="panel_not_found")
        member_ids: set[str] = set()
        member_names: dict[str, str] = {}
        voice_ids: dict[str, str] = {}
        for member in panel.members:
            if member.persona is None:
                continue
            persona = member.persona
            pid_str = persona.id
            provider = persona.live_voice_provider or settings.live_voice_provider
            if provider != "socialism":
                raise HTTPException(
                    status_code=409,
                    detail=f"expert_{pid_str}_provider_mismatch",
                )
            member_ids.add(pid_str)
            member_names[pid_str] = persona.name
            voice = (persona.live_voice or "").strip() or settings.elevenlabs_voice_id
            if not voice:
                raise HTTPException(
                    status_code=503,
                    detail=f"expert_{pid_str}_voice_not_configured",
                )
            voice_ids[pid_str] = voice
        if not member_ids:
            raise HTTPException(status_code=400, detail="panel_has_no_members")
        return (
            GroupVoiceSession(
                panel_id=panel_id,
                member_ids=member_ids,
                member_names=member_names,
            ),
            voice_ids,
        )


@dataclass
class _Call:
    session: GroupVoiceSession
    runtime: GroupVoiceAudioRuntime | None
    emit: Any
    push_snapshot: Any
    user_id: str
    customer_id: int
    speaking_task: dict[str, Any]


async def _replace_speech(speaking_task: dict[str, Any], speech) -> None:
    previous = speaking_task.get("task")
    if previous is not None and not previous.done():
        previous.cancel()
        await asyncio.gather(previous, return_exceptions=True)
    speaking_task["task"] = asyncio.create_task(speech)


async def _maybe_speak(call: _Call, user_text: str) -> None:
    if call.runtime is None or not call.session.floor:
        return
    await _replace_speech(
        call.speaking_task,
        run_floor_turn(
            session=call.session,
            runtime=call.runtime,
            user_text=user_text,
            user_id=call.user_id,
            customer_id=call.customer_id,
        ),
    )


async def _on_utterance(call: _Call, raw: dict) -> None:
    msg = HumanUtterance.model_validate(raw)
    addressed = call.session.address_by_name(msg.text)
    if addressed:
        call.session.grant_floor(addressed)
        await call.push_snapshot()
        await _maybe_speak(call, msg.text)
        return
    await call.push_snapshot()


async def _on_raise_hand(call: _Call, raw: dict) -> None:
    msg = RaiseHand.model_validate(raw)
    call.session.raise_hand(msg.persona_id)
    await call.push_snapshot()


async def _on_grant_floor(call: _Call, raw: dict) -> None:
    msg = GrantFloor.model_validate(raw)
    call.session.grant_floor(msg.persona_id)
    await call.push_snapshot()
    await _maybe_speak(call, call.session.last_utterance)


async def _on_release_floor(call: _Call, raw: dict) -> None:
    msg = ReleaseFloor.model_validate(raw)
    call.session.release_floor()
    factory = jobs_service.job_session_factory()
    async with factory() as db:
        prompts = await require_active_prompts(db)
    keep_prompt = render_prompt(prompts, "sme.group_voice.keep_hand")
    await call.session.decide_keep_hands(msg.transcript, keep_hand_prompt=keep_prompt)
    await call.push_snapshot()


async def _on_attach_tool(call: _Call, raw: dict) -> None:
    msg = AttachTool.model_validate(raw)
    call.session.attach_tool_result(msg.persona_id, msg.tool_name, msg.result, msg.summary)
    await call.push_snapshot()


async def _on_speak_as(call: _Call, raw: dict) -> None:
    msg = SpeakAs.model_validate(raw)
    if call.runtime is None:
        return
    await _replace_speech(call.speaking_task, call.runtime.speak_as(msg.persona_id, msg.text))


async def _on_commit_audio(call: _Call, _raw: dict) -> None:
    if call.runtime is not None:
        await call.runtime.commit_audio()


async def _on_clear_audio(call: _Call, _raw: dict) -> None:
    if call.runtime is not None:
        await call.runtime.clear()


async def _on_ping(call: _Call, _raw: dict) -> None:
    await call.emit({"type": "pong"})


_HANDLERS = {
    "utterance": _on_utterance,
    "raise_hand": _on_raise_hand,
    "grant_floor": _on_grant_floor,
    "release_floor": _on_release_floor,
    "attach_tool": _on_attach_tool,
    "speak_as": _on_speak_as,
    "commit_audio": _on_commit_audio,
    "clear_audio": _on_clear_audio,
    "ping": _on_ping,
}


async def _dispatch(call: _Call, raw: dict) -> None:
    kind = raw.get("type")
    handler = _HANDLERS.get(kind) if isinstance(kind, str) else None
    if handler is None:
        await call.emit({"type": "error", "detail": f"unknown type {kind}"})
        return
    await handler(call, raw)


async def _receive_loop(websocket: WebSocket, call: _Call) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        frame = message.get("bytes")
        if frame is not None:
            if call.runtime is not None:
                await call.runtime.append_audio(frame)
            continue
        text = message.get("text")
        if text is None:
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            await call.emit({"type": "error", "detail": "invalid json"})
            continue
        if not isinstance(raw, dict):
            await call.emit({"type": "error", "detail": "expected object"})
            continue
        try:
            await _dispatch(call, raw)
        except ValidationError as exc:
            await call.emit({"type": "error", "detail": str(exc.errors()[0]["msg"])})


async def _send_json(websocket: WebSocket, lock: asyncio.Lock, payload: dict) -> None:
    async with lock:
        try:
            await websocket.send_json(payload)
        except (RuntimeError, WebSocketDisconnect):
            pass


async def _send_bytes(websocket: WebSocket, lock: asyncio.Lock, payload: bytes) -> None:
    async with lock:
        try:
            await websocket.send_bytes(payload)
        except (RuntimeError, WebSocketDisconnect):
            pass


async def _start_call(websocket: WebSocket, lock: asyncio.Lock, speaking_task: dict[str, Any]) -> _Call:
    user = await _authenticate(websocket)
    raw = await websocket.receive_json()
    start = StartSession.model_validate(raw)
    session, voice_ids = await _load_panel_session(start.panel_id, user)

    async def emit(payload: dict) -> None:
        await _send_json(websocket, lock, payload)

    async def emit_audio(payload: bytes) -> None:
        await _send_bytes(websocket, lock, payload)

    async def push_snapshot() -> None:
        await emit({"type": "snapshot", **session.snapshot()})

    call = _Call(
        session=session,
        runtime=None,
        emit=emit,
        push_snapshot=push_snapshot,
        user_id=user.id,
        customer_id=user.kund_id or 0,
        speaking_task=speaking_task,
    )

    async def on_floor_granted(_persona_id: str, transcript: str) -> None:
        await _maybe_speak(call, transcript)

    call.runtime = GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language=start.language, voice_ids=voice_ids),
        emit_json=emit,
        emit_audio=emit_audio,
        on_floor_granted=on_floor_granted,
    )
    await call.runtime.start()
    await emit(
        {
            "type": "ready",
            "panel_id": session.panel_id,
            "audio_format": {"codec": "pcm16", "sample_rate": 24000, "channels": 1},
        }
    )
    await push_snapshot()
    return call


async def _stop_call(websocket: WebSocket, speaking_task: dict[str, Any], runtime: GroupVoiceAudioRuntime | None) -> None:
    task = speaking_task.get("task")
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if runtime is not None:
        await runtime.close()
    try:
        await websocket.close()
    except (RuntimeError, WebSocketDisconnect):
        pass


@router.websocket("/ws/sme-group-voice")
async def sme_group_voice_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    await _serve(websocket)


async def _serve(websocket: WebSocket) -> None:
    lock = asyncio.Lock()
    speaking_task: dict[str, Any] = {"task": None}
    runtime: GroupVoiceAudioRuntime | None = None
    try:
        call = await _start_call(websocket, lock, speaking_task)
        runtime = call.runtime
        await _receive_loop(websocket, call)
    except HTTPException as exc:
        await _send_json(websocket, lock, {"type": "error", "detail": str(exc.detail)})
        await websocket.close(code=4403)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("SME group voice WebSocket failed")
        await _send_json(websocket, lock, {"type": "error", "detail": "internal"})
    finally:
        await _stop_call(websocket, speaking_task, runtime)
