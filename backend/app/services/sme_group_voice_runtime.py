"""Audio runtime for SME panel group voice sessions.

Reuses the existing OpenAI STT and ElevenLabs TTS providers.
Control state lives in GroupVoiceSession; this class only handles
audio frames, transcripts, and floor-driven speech synthesis.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from openai import OpenAIError

from app.config import settings
from app.services.elevenlabs_tts import ElevenLabsTts
from app.services.openai_live_transcription import (
    OpenAITranscriptionStream,
    TranscriptEvent,
)
from app.services.sme_group_voice import GroupVoiceSession

logger = logging.getLogger(__name__)

EmitJson = Callable[[dict], Awaitable[None]]
EmitAudio = Callable[[bytes], Awaitable[None]]


@dataclass
class GroupVoiceAudioScope:
    language: str
    # persona_id -> elevenlabs voice_id
    voice_ids: dict[str, str]


class GroupVoiceAudioRuntime:
    """One audio pipeline per panel voice WebSocket."""

    def __init__(
        self,
        session: GroupVoiceSession,
        scope: GroupVoiceAudioScope,
        *,
        emit_json: EmitJson,
        emit_audio: EmitAudio,
    ) -> None:
        self.session = session
        self.scope = scope
        self._emit_json = emit_json
        self._emit_audio = emit_audio
        self._stt = OpenAITranscriptionStream(
            api_key=settings.openai_api_key,
            model=settings.live_speech_stt_model,
            language=scope.language,
            on_event=self._on_transcript,
        )
        self._tts_cache: dict[str, ElevenLabsTts] = {}
        self._closed = False
        self._speaking_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._stt.start()

    async def append_audio(self, frame: bytes) -> None:
        if self._closed:
            return
        if len(frame) == 0 or len(frame) % 2 or len(frame) > 9600:
            raise ValueError("invalid_audio_frame")
        await self._stt.append(frame)

    async def commit_audio(self) -> None:
        await self._stt.commit()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._speaking_task is not None and not self._speaking_task.done():
            self._speaking_task.cancel()
            await asyncio.gather(self._speaking_task, return_exceptions=True)
        await self._stt.close()

    async def _on_transcript(self, event: TranscriptEvent) -> None:
        if self._closed or event.kind != "final":
            return
        text = (event.text or "").strip()
        if not text:
            return
        await self._emit_json(
            {
                "type": "transcript.final",
                "text": text,
                "item_id": event.item_id or "pending",
            }
        )
        addressed = self.session.address_by_name(text)
        if addressed:
            self.session.grant_floor(addressed)
            await self._emit_json({"type": "snapshot", **self.session.snapshot()})
            await self._emit_json(
                {
                    "type": "floor.granted",
                    "persona_id": addressed,
                    "floor_name": self.session.member_names.get(addressed),
                }
            )

    async def speak_as(self, persona_id: str, text: str) -> None:
        """Synthesize and stream audio for the expert who currently holds the floor."""
        if self._closed or self.session.floor != persona_id:
            return
        voice_id = self.scope.voice_ids.get(persona_id)
        if not voice_id:
            await self._emit_json(
                {"type": "error", "detail": f"no_voice_for_{persona_id}"}
            )
            return
        tts = self._tts_for(voice_id)
        turn_id = str(uuid4())
        await self._emit_json(
            {
                "type": "assistant.speaking",
                "persona_id": persona_id,
                "turn_id": turn_id,
                "text": text,
            }
        )
        try:
            async for chunk in tts.stream(text, language=self.scope.language):
                if self._closed or self.session.floor != persona_id:
                    break
                await self._emit_audio(chunk)
        except (ElevenLabsApiError, OpenAIError) as exc:
            logger.warning("group voice TTS failed: %s", exc)
            await self._emit_json({"type": "error", "detail": "tts_failed"})
        finally:
            if self.session.floor == persona_id:
                self.session.release_floor()
                await self._emit_json({"type": "snapshot", **self.session.snapshot()})
            await self._emit_json(
                {"type": "assistant.done", "persona_id": persona_id, "turn_id": turn_id}
            )

    def _tts_for(self, voice_id: str) -> ElevenLabsTts:
        cached = self._tts_cache.get(voice_id)
        if cached is not None:
            return cached
        tts = ElevenLabsTts(
            api_key=settings.elevenlabs_api_key,
            voice_id=voice_id,
            model_id=settings.live_speech_tts_model,
            output_format=settings.live_speech_tts_output_format,
        )
        self._tts_cache[voice_id] = tts
        return tts
