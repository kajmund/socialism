"""Audio runtime for SME panel group voice sessions.

Reuses the existing OpenAI STT and ElevenLabs TTS providers.
Control state lives in GroupVoiceSession; this class only handles
audio frames, transcripts, and floor-driven speech synthesis.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from openai import OpenAIError

from app.config import settings
from app.live_speech_settings import tts_sample_rate
from app.services.elevenlabs_tts import ElevenLabsTts
from app.services.live_speech_backchannel import SpeechBarge
from app.services.live_speech_coordinator import SpeechResponseCoordinator
from app.services.openai_live_transcription import (
    OpenAITranscriptionStream,
    TranscriptEvent,
)
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_names import correct_names, name_bias_prompt
from app.services.sme_open_document import workspace_tool_delivery_key

logger = logging.getLogger(__name__)

EmitJson = Callable[[dict], Awaitable[None]]
EmitAudio = Callable[[bytes], Awaitable[None]]
OnFloorGranted = Callable[[str, str], Awaitable[None]]  # persona_id, transcript
OnUnaddressed = Callable[[str], Awaitable[None]]
OnBargeIn = Callable[[], Awaitable[None]]


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
        on_floor_granted: OnFloorGranted | None = None,
        on_unaddressed: OnUnaddressed | None = None,
    ) -> None:
        self.session = session
        self.scope = scope
        self._emit_json = emit_json
        self._emit_audio = emit_audio
        self._on_floor_granted = on_floor_granted
        self._on_unaddressed = on_unaddressed
        self.interrupt_speech: OnBargeIn | None = None
        self._stt = OpenAITranscriptionStream(
            api_key=settings.openai_api_key,
            model=settings.live_speech_stt_model,
            language=scope.language,
            prompt=name_bias_prompt(list(session.member_names.values())),
            keywords=list(session.member_names.values()),
            on_event=self._on_transcript,
        )
        self._tts_cache: dict[str, ElevenLabsTts] = {}
        self._closed = False
        self._speaking_task: asyncio.Task[None] | None = None
        self._hand_task: asyncio.Task[None] | None = None
        self._barge = SpeechBarge(self._barge_in)
        self._coordinator: SpeechResponseCoordinator | None = None
        self._sequence = 0

    async def emit_workspace_tool(self, calls: list[dict], *, expert_id: str | None = None) -> None:
        """One speaker's document open, and every passage that speaker marks."""
        sent: set[tuple[str, ...]] = set()
        for call in calls:
            arguments = dict(call.get("arguments") or {})
            name = str(call.get("name") or "")
            key = workspace_tool_delivery_key(name, arguments, expert_id)
            if not name or key in sent:
                continue
            sent.add(key)
            if name == "focus_anchor" and expert_id:
                arguments["expert_id"] = expert_id
            await self._emit_json({
                "type": "workspace.tool",
                "name": name,
                "arguments": arguments,
            })

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

    async def clear(self) -> None:
        await self._stt.clear()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._speaking_task is not None and not self._speaking_task.done():
            self._speaking_task.cancel()
            await asyncio.gather(self._speaking_task, return_exceptions=True)
        if self._hand_task is not None and not self._hand_task.done():
            self._hand_task.cancel()
            await asyncio.gather(self._hand_task, return_exceptions=True)
        await self._barge.aclose()
        await self._stt.close()

    async def _on_transcript(self, event: TranscriptEvent) -> None:
        if self._closed or event.kind not in {"final", "partial"}:
            return
        text = (event.text or "").strip()
        if not text:
            return
        if event.kind == "partial":
            await self._emit_json({"type": "transcript.partial", "text": text})
            if self.session.floor is not None:
                await self._barge.consider(text, final=False)
            return
        text = correct_names(text, self.session.member_names)
        if self.session.floor is not None and await self._barge.consider(text, final=True):
            return
        await self._apply_final(text, event.item_id)

    async def _barge_in(self, _reason: str) -> None:
        if self._closed or self.session.floor is None:
            return
        hand = self._hand_task
        self._hand_task = None
        if hand is not None and not hand.done():
            hand.cancel()
            await asyncio.gather(hand, return_exceptions=True)
        if self._coordinator is not None:
            self._coordinator.interrupt_playback()
        if self.session.floor is not None:
            self.session.release_floor()
        if self._closed:
            return
        await self._emit_json({"type": "assistant.cancelled"})
        await self._emit_json({"type": "snapshot", **self.session.snapshot()})
        if self.interrupt_speech is not None:
            await self.interrupt_speech()
        logger.info("group voice barge_in")

    async def _apply_final(self, text: str, item_id: str | None) -> None:
        await self._emit_json(
            {
                "type": "transcript.final",
                "text": text,
                "item_id": item_id or "pending",
            }
        )
        self.session.last_utterance = text
        addressed = self.session.address_by_name(text)
        if self.session.floor:
            if addressed and addressed != self.session.floor:
                self.session.raise_hand(addressed)
                await self._emit_json({"type": "snapshot", **self.session.snapshot()})
                return
            await self._schedule_hands(text)
            return
        if addressed:
            await self._grant(addressed, text)
            return
        await self._schedule_hands(text)

    async def _grant(self, persona_id: str, text: str) -> None:
        self.session.grant_floor(persona_id)
        await self._emit_json({"type": "snapshot", **self.session.snapshot()})
        await self._emit_json(
            {
                "type": "floor.granted",
                "persona_id": persona_id,
                "floor_name": self.session.member_names.get(persona_id),
            }
        )
        if self._on_floor_granted is not None:
            await self._on_floor_granted(persona_id, text)

    async def _schedule_hands(self, text: str) -> None:
        """Decide hands off the transcription reader so a slow call cannot drop the socket."""
        if self._on_unaddressed is None:
            return
        previous = self._hand_task
        if previous is not None and not previous.done():
            previous.cancel()
            await asyncio.gather(previous, return_exceptions=True)
        self._hand_task = asyncio.create_task(self._decide_hands(text))

    async def _decide_hands(self, text: str) -> None:
        try:
            if self._on_unaddressed is not None:
                await self._on_unaddressed(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("group voice hand decision failed")
            if not self._closed:
                await self._emit_json({"type": "error", "detail": "hand_decision_failed"})
                await self._emit_json({"type": "listening"})
            return
        if self._closed:
            return
        await self._emit_json({"type": "snapshot", **self.session.snapshot()})
        if self.session.floor is None:
            await self._emit_json({"type": "listening"})

    async def release_unspoken(self, persona_id: str) -> None:
        """Drop a floor that produced no speech so the next utterance can be heard."""
        if self.session.floor != persona_id:
            return
        self.session.release_floor()
        await self._emit_json({"type": "snapshot", **self.session.snapshot()})
        await self._emit_json(
            {"type": "assistant.done", "persona_id": persona_id, "turn_id": ""}
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
            await self._playback(voice_id).play_main(text, turn_id)
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

    def _playback(self, voice_id: str) -> SpeechResponseCoordinator:
        """Pace this reply the same way a single expert does, so barge-in can cut it."""
        tts = self._tts_for(voice_id)

        async def stream(text: str) -> AsyncIterator[bytes]:
            async for chunk in tts.stream(text, language=self.scope.language):
                yield chunk

        coordinator = SpeechResponseCoordinator(
            stream=stream,
            emit_json=self._emit_json,
            emit_audio=self._emit_audio,
            sample_rate=tts_sample_rate(settings.live_speech_tts_output_format),
            next_sequence=self._next_sequence,
        )
        self._coordinator = coordinator
        return coordinator

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

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
