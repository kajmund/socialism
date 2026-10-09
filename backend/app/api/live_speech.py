"""Authenticated mixed JSON/binary WebSocket for SME Live Speech."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from time import monotonic

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from openai import OpenAIError
from pydantic import ValidationError
from websockets.exceptions import ConnectionClosedError

from app.auth.tokens import user_from_bearer_token
from app.config import settings
from app.database.models import Kund, UserAccount
from app.schemas.live_speech import (
    AudioCancel,
    AudioCommit,
    AudioStart,
    ClientControl,
    ClientPing,
    SessionMute,
    SessionStart,
    SessionStop,
    TurnCancel,
    client_control_adapter,
)
from app.schemas.workspace import WorkspaceState
from app.services import jobs as jobs_service
from app.services.live_speech_admit import recent_interview_turns
from app.services.live_speech_runtime import LiveSpeechRuntime, LiveSpeechScope
from app.services.live_speech_sessions import LiveSpeechLease, LiveSpeechRegistry
from app.services.prompt_store import require_prompts_for_persona
from app.services.workspace.service import require_expert, require_workspace

router = APIRouter(tags=["websocket"])


async def _authenticate(websocket: WebSocket) -> UserAccount:
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        return await user_from_bearer_token(
            session,
            websocket.query_params.get("access_token"),
        )


async def _scope(start: SessionStart, user: UserAccount) -> LiveSpeechScope:
    if user.kund_id is None:
        raise HTTPException(status_code=403, detail="kund_access_denied")
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        kund = await session.get(Kund, user.kund_id)
        if kund is None or kund.product != "sme":
            raise HTTPException(status_code=403, detail="sme_product_required")
        workspace = await require_workspace(session, start.workspace_id, user)
        expert = await require_expert(session, workspace, start.expert_id)
        prompts = await require_prompts_for_persona(session, expert, language=start.language)
        provider = expert.live_voice_provider or settings.live_voice_provider
        if provider != "socialism":
            raise HTTPException(status_code=409, detail="live_speech_provider_mismatch")
        voice_id = (expert.live_voice or "").strip() or settings.elevenlabs_voice_id
        if not voice_id:
            raise HTTPException(status_code=503, detail="live_speech_tts_not_configured")
        state = WorkspaceState.model_validate(workspace.state)
        state.expert_id = start.expert_id
        recent_turns = await recent_interview_turns(session, start.expert_id)
        await session.rollback()
    return LiveSpeechScope(
        user_id=user.id,
        customer_id=user.kund_id,
        workspace_id=start.workspace_id,
        expert_id=start.expert_id,
        language=start.language,
        voice_id=voice_id,
        workspace_state=state,
        prompts=prompts,
        recent_turns=recent_turns,
    )


def _require_provider_configuration() -> None:
    if not settings.openai_api_key.strip():
        raise HTTPException(status_code=503, detail="live_speech_openai_not_configured")
    if not settings.elevenlabs_api_key.strip():
        raise HTTPException(status_code=503, detail="live_speech_tts_not_configured")


class LiveSpeechSocket:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.send_lock = asyncio.Lock()
        self.runtime: LiveSpeechRuntime | None = None
        self.lease: LiveSpeechLease | None = None
        self.started_at = monotonic()
        self.output_sequence = 0

    async def emit_json(self, payload: dict) -> None:
        lease_fields = (
            {"voice_session_id": self.lease.id, "generation": self.lease.generation}
            if self.lease is not None
            else {}
        )
        async with self.send_lock:
            self.output_sequence += 1
            await self.websocket.send_json(
                {
                    **payload,
                    **lease_fields,
                    "sequence": self.output_sequence,
                }
            )

    async def emit_audio(self, payload: bytes) -> None:
        async with self.send_lock:
            await self.websocket.send_bytes(payload)

    async def setup(self) -> None:
        user = await _authenticate(self.websocket)
        first = await _receive_control(self.websocket)
        if not isinstance(first, SessionStart):
            raise HTTPException(status_code=422, detail="session_start_required")
        _require_provider_configuration()
        scope = await _scope(first, user)
        self.runtime = LiveSpeechRuntime(
            scope,
            emit_json=self.emit_json,
            emit_audio=self.emit_audio,
        )
        registry: LiveSpeechRegistry = self.websocket.app.state.live_speech_registry
        self.lease = await registry.claim(
            user_id=scope.user_id,
            customer_id=scope.customer_id,
            workspace_id=scope.workspace_id,
            expert_id=scope.expert_id,
            language=scope.language,
            close=self.revoke,
        )
        await self.runtime.start()
        await self.emit_json(
            {
                "type": "session.ready",
                "audio_format": {
                    "codec": "pcm16",
                    "sample_rate": 24000,
                    "channels": 1,
                },
                "stt_model": settings.live_speech_stt_model,
                "vad": {
                    "threshold": settings.live_speech_vad_threshold,
                    "preroll_ms": settings.live_speech_vad_preroll_ms,
                    "hangover_ms": settings.live_speech_vad_hangover_ms,
                    "min_speech_ms": settings.live_speech_vad_min_speech_ms,
                    "urgent_ms": settings.live_speech_vad_urgent_ms,
                },
            }
        )
        await self.emit_json({"type": "session.state", "state": "listening"})

    async def receive_loop(self) -> None:
        while True:
            remaining = settings.live_speech_session_ttl_seconds - (
                monotonic() - self.started_at
            )
            if remaining <= 0:
                raise TimeoutError
            timeout = min(settings.live_speech_idle_timeout_seconds, remaining)
            async with asyncio.timeout(timeout):
                message = await self.websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            frame = message.get("bytes")
            if frame is not None:
                await self._required_runtime().append_audio(frame)
                continue
            text = message.get("text")
            if text is None:
                raise ValueError("invalid_websocket_frame")
            event = client_control_adapter.validate_json(text)
            if await self.dispatch(event):
                return

    async def dispatch(self, event: ClientControl) -> bool:
        runtime = self._required_runtime()
        if isinstance(event, SessionStart):
            raise ValueError("session_already_started")
        if isinstance(event, AudioStart):
            await runtime.audio_started(event.sequence)
        elif isinstance(event, AudioCommit):
            await runtime.commit_audio(event.sequence)
        elif isinstance(event, AudioCancel):
            await runtime.cancel_audio()
        elif isinstance(event, TurnCancel):
            await runtime.cancel_turn(event.turn_id, event.reason)
        elif isinstance(event, SessionMute):
            await runtime.set_muted(event.muted)
        elif isinstance(event, SessionStop):
            await runtime.close(event.reason)
            return True
        elif isinstance(event, ClientPing):
            await self.emit_json(
                {
                    "type": "server.pong",
                    "client_sequence": event.sequence,
                    "server_time": datetime.now(UTC).isoformat(),
                }
            )
        return False

    async def close(self) -> None:
        if self.runtime is not None:
            await asyncio.gather(
                self.runtime.close("socket_closed"),
                return_exceptions=True,
            )
        if self.lease is not None:
            registry: LiveSpeechRegistry = self.websocket.app.state.live_speech_registry
            await registry.release(self.lease)

    async def revoke(self, reason: str) -> None:
        if self.runtime is not None:
            await asyncio.gather(self.runtime.close(reason), return_exceptions=True)
        await asyncio.gather(
            self.websocket.close(code=4001, reason=reason),
            return_exceptions=True,
        )

    def _required_runtime(self) -> LiveSpeechRuntime:
        if self.runtime is None:
            raise RuntimeError("session_not_started")
        return self.runtime


@router.websocket("/ws/live-speech")
async def live_speech_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    socket = LiveSpeechSocket(websocket)
    try:
        await socket.setup()
        await socket.receive_loop()
    except TimeoutError:
        await _safe_error(socket.emit_json, "session_idle_timeout", "Voice session timed out", False)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        await _safe_error(socket.emit_json, "invalid_event", str(exc), False)
    except HTTPException as exc:
        await _safe_error(socket.emit_json, str(exc.detail), str(exc.detail), False)
    except (ConnectionClosedError, OpenAIError, RuntimeError):
        await _safe_error(
            socket.emit_json,
            "live_speech_provider_failed",
            "Live Speech provider failed",
            False,
        )
    except WebSocketDisconnect:
        pass
    finally:
        await socket.close()


async def _receive_control(websocket: WebSocket):
    raw = await websocket.receive_text()
    return client_control_adapter.validate_json(raw)


async def _safe_error(
    emit_json,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    try:
        await emit_json(
            {
                "type": "session.error",
                "code": code,
                "message": message,
                "retryable": retryable,
            }
        )
    except (RuntimeError, WebSocketDisconnect):
        pass
