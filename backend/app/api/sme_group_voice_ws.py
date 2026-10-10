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
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.auth.tokens import user_from_bearer_token
from app.config import settings
from app.database.models import Kund, Population, PopulationMember, UserAccount
from app.services import jobs as jobs_service
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


async def _maybe_speak(
    *,
    session: GroupVoiceSession,
    runtime: GroupVoiceAudioRuntime | None,
    user_text: str,
    user_id: str,
) -> None:
    if runtime is None or not session.floor:
        return
    await run_floor_turn(
        session=session,
        runtime=runtime,
        user_text=user_text,
        user_id=user_id,
    )


async def _dispatch(
    *,
    kind: str,
    raw: dict,
    session: GroupVoiceSession,
    runtime: GroupVoiceAudioRuntime | None,
    emit,
    push_snapshot,
    user_id: str,
) -> None:
    if kind == "utterance":
        msg = HumanUtterance.model_validate(raw)
        addressed = session.address_by_name(msg.text)
        if addressed:
            session.grant_floor(addressed)
            await push_snapshot()
            await _maybe_speak(
                session=session,
                runtime=runtime,
                user_text=msg.text,
                user_id=user_id,
            )
        else:
            await push_snapshot()
    elif kind == "raise_hand":
        msg = RaiseHand.model_validate(raw)
        session.raise_hand(msg.persona_id)
        await push_snapshot()
    elif kind == "grant_floor":
        msg = GrantFloor.model_validate(raw)
        session.grant_floor(msg.persona_id)
        await push_snapshot()
        await _maybe_speak(
            session=session,
            runtime=runtime,
            user_text="(floor granted)",
            user_id=user_id,
        )
    elif kind == "release_floor":
        msg = ReleaseFloor.model_validate(raw)
        session.release_floor()
        await session.decide_keep_hands(msg.transcript)
        await push_snapshot()
    elif kind == "attach_tool":
        msg = AttachTool.model_validate(raw)
        session.attach_tool_result(
            msg.persona_id,
            msg.tool_name,
            msg.result,
            msg.summary,
        )
        await push_snapshot()
    elif kind == "speak_as":
        msg = SpeakAs.model_validate(raw)
        if runtime is not None:
            await runtime.speak_as(msg.persona_id, msg.text)
    elif kind == "commit_audio":
        if runtime is not None:
            await runtime.commit_audio()
    elif kind == "ping":
        await emit({"type": "pong"})
    else:
        await emit({"type": "error", "detail": f"unknown type {kind}"})


async def _receive_loop(
    websocket: WebSocket,
    *,
    session: GroupVoiceSession,
    runtime: GroupVoiceAudioRuntime | None,
    emit,
    push_snapshot,
    user_id: str,
) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        frame = message.get("bytes")
        if frame is not None:
            if runtime is not None:
                await runtime.append_audio(frame)
            continue
        text = message.get("text")
        if text is None:
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            await emit({"type": "error", "detail": "invalid json"})
            continue
        if not isinstance(raw, dict):
            await emit({"type": "error", "detail": "expected object"})
            continue
        kind = raw.get("type")
        try:
            await _dispatch(
                kind=kind,
                raw=raw,
                session=session,
                runtime=runtime,
                emit=emit,
                push_snapshot=push_snapshot,
                user_id=user_id,
            )
        except ValidationError as exc:
            await emit({"type": "error", "detail": str(exc.errors()[0]["msg"])})


@router.websocket("/ws/sme-group-voice")
async def sme_group_voice_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    session: GroupVoiceSession | None = None
    runtime: GroupVoiceAudioRuntime | None = None
    send_lock = asyncio.Lock()

    async def emit(payload: dict) -> None:
        async with send_lock:
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                pass

    async def emit_audio(payload: bytes) -> None:
        async with send_lock:
            try:
                await websocket.send_bytes(payload)
            except (RuntimeError, WebSocketDisconnect):
                pass

    async def push_snapshot() -> None:
        if session is not None:
            await emit({"type": "snapshot", **session.snapshot()})

    try:
        user = await _authenticate(websocket)
        raw = await websocket.receive_json()
        start = StartSession.model_validate(raw)
        session, voice_ids = await _load_panel_session(start.panel_id, user)
        scope = GroupVoiceAudioScope(language=start.language, voice_ids=voice_ids)
        runtime = GroupVoiceAudioRuntime(
            session,
            scope,
            emit_json=emit,
            emit_audio=emit_audio,
        )
        await runtime.start()
        await emit(
            {
                "type": "ready",
                "panel_id": session.panel_id,
                "audio_format": {
                    "codec": "pcm16",
                    "sample_rate": 24000,
                    "channels": 1,
                },
            }
        )
        await push_snapshot()
        await _receive_loop(
            websocket,
            session=session,
            runtime=runtime,
            emit=emit,
            push_snapshot=push_snapshot,
            user_id=user.id,
        )
    except HTTPException as exc:
        await emit({"type": "error", "detail": str(exc.detail)})
        await websocket.close(code=4403)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("SME group voice WebSocket failed")
        await emit({"type": "error", "detail": "internal"})
    finally:
        if runtime is not None:
            await runtime.close()
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
