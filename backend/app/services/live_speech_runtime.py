"""Provider and canonical-chat orchestration for one Live Speech socket."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from time import monotonic
from uuid import uuid4

from app.config import settings
from app.live_speech_settings import tts_sample_rate
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.services import jobs as jobs_service
from app.services.conversation_controller import ConversationController, ConversationEvent
from app.services.elevenlabs_tts import ElevenLabsTts
from app.services.latency_stats import LatencyStats
from app.services.live_speech_coordinator import SpeechResponseCoordinator
from app.services.live_speech_cues import LiveSpeechCues
from app.services.live_speech_history import persist_interrupted_voice_turn
from app.services.live_speech_scope import LiveSpeechScope
from app.services.live_speech_speculation import SpeculativeReader
from app.services.live_speech_traces import forward_library_trace
from app.services.live_speech_turn_run import run_voice_turn
from app.services.live_speech_focus import focus_sources as _focus_sources
from app.services.live_speech_correction import (
    CORRECTION_PROMPT_KEY,
    correct_transcript,
)
from app.services.live_speech_offline import MAX_UTTERANCE_BYTES, OfflineTranscriber
from app.services.openai_live_transcription import (
    OpenAITranscriptionStream,
    TranscriptEvent,
)
from app.services.tts_cache import cached_tts
from app.services.workspace_tool_delivery import voice_tool_callback

EmitJson = Callable[[dict], Awaitable[None]]
EmitAudio = Callable[[bytes], Awaitable[None]]
logger = logging.getLogger(__name__)


class LiveSpeechRuntime:
    def __init__(
        self,
        scope: LiveSpeechScope,
        *,
        emit_json: EmitJson,
        emit_audio: EmitAudio,
    ) -> None:
        self.scope = scope
        self._emit_json = emit_json
        self._emit_audio = emit_audio
        self._base_keywords = list(scope.stt_base_keywords)
        self._stt = OpenAITranscriptionStream(
            api_key=settings.openai_api_key,
            model=settings.live_speech_stt_model,
            language=scope.language,
            prompt=scope.stt_prompt,
            keywords=list(scope.stt_keywords),
            on_event=self._on_transcript,
        )
        self._tts = cached_tts(
            ElevenLabsTts,
            api_key=settings.elevenlabs_api_key, voice_id=scope.voice_id,
            model_id=settings.live_speech_tts_model,
            output_format=settings.live_speech_tts_output_format,
            cache_dir=settings.tts_cache_dir, max_bytes=settings.tts_cache_max_bytes)
        self._offline = OfflineTranscriber()
        self._offline_task: asyncio.Task[str | None] | None = None
        self._utterance_open = False
        self._utterance_pcm: list[bytes] = []
        self._utterance_samples = 0
        self._correction_history: list[tuple[str, str]] = [(role, text) for role, text in scope.recent_turns][-6:]
        self._partials: dict[str, str] = {}
        self._revisions: dict[str, int] = {}
        self._turn_task: asyncio.Task[None] | None = None
        self._turn_cancel = asyncio.Event()
        self._turn_id: str | None = None
        self._muted = False
        self._closed = False
        self._sequence = 0
        self._last_audio_sequence = -1
        self._commit_timeout: asyncio.Task[None] | None = None
        self._spoken_text = ""
        self._user_text = ""
        self._assistant_text = ""
        self._voiced_reply = ""
        self._request_id: str | None = None
        self._request_fence: int | None = None
        self._speech_started_at: float | None = None
        self._commit_at: float | None = None
        self._final_at: float | None = None
        self._first_partial_logged = False
        self._first_delta_logged = False
        self._first_audio_logged = False
        self._user_text_partial = ""
        self._conversation = ConversationController()
        self._metrics = LatencyStats(logger)
        self._commit_seq = 0
        self._item_commit: dict[str, int] = {}
        self._item_epoch: dict[str, str] = {}
        self._utterance_id: str | None = None
        self._pending_final: ConversationEvent | None = None
        self._speculation = SpeculativeReader(
            workspace_id=scope.workspace_id,
            user_id=scope.user_id,
            workspace_state=scope.workspace_state,
            min_chars=settings.live_speech_speculation_min_chars,
            enabled=settings.live_speech_speculation_enabled,
            customer_id=scope.customer_id,
        )
        self._cues = LiveSpeechCues(self)
        self._coordinator = SpeechResponseCoordinator(
            stream=self._tts_chunks,
            emit_json=self._emit_json,
            emit_audio=self._emit_audio,
            sample_rate=tts_sample_rate(settings.live_speech_tts_output_format),
            next_sequence=self._next_sequence,
            on_state=self._state,
            on_first_audio=self._mark_first_audio,
        )

    async def focus_sources(self, source_ids: list[str]) -> None:
        """Reauthorize each source against the readable scope before STT keywords."""
        await _focus_sources(self, source_ids)

    async def start(self) -> None:
        await library_chat_broadcast.subscribe_persona(
            self.scope.customer_id,
            self.scope.expert_id,
            self._on_library_event,
        )
        self._cues.start_opening()
        await self._stt.start()

    async def append_audio(self, frame: bytes) -> None:
        if self._closed or self._muted:
            return
        if len(frame) == 0 or len(frame) % 2 or len(frame) > 9600:
            raise ValueError("invalid_audio_frame")
        await self._stt.append(frame)
        if (
            self._utterance_open
            and self._offline.enabled
            and self._utterance_samples < MAX_UTTERANCE_BYTES
        ):
            self._utterance_pcm.append(frame)
            self._utterance_samples += len(frame)

    async def audio_started(self, sequence: int) -> None:
        self._advance_audio_sequence(sequence)
        if self._offline_task is not None:
            self._offline_task.cancel()
            self._offline_task = None
        self._utterance_open = True
        self._utterance_pcm = []
        self._utterance_samples = 0
        self._speech_started_at = monotonic()
        self._commit_at = None
        self._first_partial_logged = False
        self._user_text_partial = ""
        self._utterance_id = str(sequence)
        self._conversation.handle(
            ConversationEvent(kind="user_vad_start", utterance_id=self._utterance_id),
        )
        self._cues.restart_listener()

    async def commit_audio(self, sequence: int, item_id: str | None = None) -> None:
        self._advance_audio_sequence(sequence)
        self._commit_at = monotonic()
        self._commit_seq += 1
        if item_id:
            self._item_commit[item_id] = self._commit_seq
        self._conversation.handle(
            ConversationEvent(
                kind="user_vad_commit",
                sequence=self._commit_seq,
                utterance_id=item_id,
            )
        )
        self._cues.stop_listener()
        self._coordinator.drop_aside()
        self._utterance_open = False
        pcm = b"".join(self._utterance_pcm) if self._utterance_pcm else b""
        self._utterance_pcm = []
        self._utterance_samples = 0
        if pcm and self._offline.enabled:
            self._offline_task = asyncio.create_task(
                self._offline.transcribe(pcm, self.scope.language)
            )
        await self._stt.commit()
        if self._commit_timeout is not None:
            self._commit_timeout.cancel()
        self._commit_timeout = asyncio.create_task(self._await_final())

    async def cancel_audio(self) -> None:
        if self._offline_task is not None:
            self._offline_task.cancel()
            self._offline_task = None
        self._utterance_open = False
        self._utterance_pcm = []
        self._utterance_samples = 0
        await self._stt.clear()
        self._partials.clear()
        await self._state("listening")

    async def set_muted(self, muted: bool) -> None:
        self._muted = muted
        await self._state("paused" if muted else "listening")

    async def cancel_turn(self, turn_id: str | None, reason: str) -> None:
        task = self._turn_task
        if task is None or task.done():
            return
        decision = self._conversation.handle(
            ConversationEvent(kind="cancel", turn_id=turn_id),
        )
        if not decision.accepted:
            return
        cancelled_at = monotonic()
        self._turn_cancel.set()
        self._coordinator.interrupt_playback()
        self._cues.cancel_waiting()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if self._request_id is not None and self._request_fence is not None:
            await persist_interrupted_voice_turn(
                jobs_service.job_session_factory(),
                request_id=self._request_id,
                fence=self._request_fence,
                turn_id=turn_id,
                persona_id=self.scope.expert_id,
                user_text=self._user_text,
                assistant_text=self._assistant_text,
            )
        self._turn_task = None
        self._turn_id = None
        self._request_id = None
        self._request_fence = None
        await asyncio.gather(
            self._emit_json(
                {
                    "type": "assistant.cancelled",
                    "turn_id": turn_id,
                    "reason": reason,
                    "spoken_text": self._spoken_text,
                }
            ),
            return_exceptions=True,
        )
        self._metrics.add("server.turn_cancelled", (monotonic() - cancelled_at) * 1000)
        await asyncio.gather(self._state("listening"), return_exceptions=True)

    async def close(self, reason: str) -> None:
        if self._closed:
            return
        if self._turn_task is not None and not self._turn_task.done():
            await self.cancel_turn(self._turn_id, reason)
        self._closed = True
        if self._commit_timeout is not None:
            self._commit_timeout.cancel()
        if self._turn_task is not None:
            self._turn_task.cancel()
        await asyncio.gather(
            *(
                task
                for task in (
                    self._commit_timeout,
                    self._turn_task,
                    *self._cues.cancel_all(),
                )
                if task is not None
            ),
            return_exceptions=True,
        )
        await library_chat_broadcast.unsubscribe(self._on_library_event)
        await self._stt.close()
        if self._offline_task is not None:
            self._offline_task.cancel()
            self._offline_task = None
        await self._offline.aclose()
        await self._speculation.aclose()
        await self._emit_json(
            {
                "type": "session.metrics",
                "latency": self._metrics.summary(),
                "speculation": self._speculation.stats,
            }
        )
        await self._emit_json({"type": "session.state", "state": "closed", "reason": reason})

    async def _on_transcript(self, event: TranscriptEvent) -> None:
        if self._closed:
            return
        if event.kind == "error":
            await self._error(
                event.code or "stt_provider_error",
                "Transcription failed",
                False,
            )
            return
        item_id = event.item_id or "pending"
        if event.kind == "partial":
            await self._cues.on_partial(item_id, event.text)
            self._speculation.on_partial(event.text)
            return
        await self._on_final_transcript(item_id, event.text)

    async def _on_final_transcript(self, item_id: str, raw: str) -> None:
        if self._commit_timeout is not None:
            self._commit_timeout.cancel()
            self._commit_timeout = None
        final_event = ConversationEvent(
            kind="user_final",
            sequence=self._item_commit.get(item_id, self._commit_seq),
            utterance_id=self._item_epoch.get(item_id, self._utterance_id),
        )
        if self._conversation.reject_reason(final_event) is not None:
            return
        text = await self._canonical_text(raw.strip())
        if not text:
            await self._error("empty_transcript", "No speech was transcribed", True)
            return
        if self._cues.echoes_listener(text):
            return
        self._final_at = monotonic()
        self._first_delta_logged = False
        self._first_audio_logged = False
        if self._commit_at is not None:
            self._metrics.add(
                "provider.final_transcript", (self._final_at - self._commit_at) * 1000,
            )
        if self._conversation.reject_reason(final_event) is not None:
            return
        if self._cues.assistant_active() and await self._cues.classify_user_speech(
            text, final=True
        ):
            return
        self._pending_final = final_event
        await self._begin_turn(item_id, text)

    async def _canonical_text(self, streaming: str) -> str:
        chosen = await self._prefer_offline(streaming)
        if chosen and self.scope.correction_enabled:
            chosen = await self._correct(chosen)
        return chosen

    async def _prefer_offline(self, streaming: str) -> str:
        """Offline second pass within the grace window; streaming text on failure."""
        chosen = streaming
        task = self._offline_task
        self._offline_task = None
        if task is None:
            return chosen
        try:
            if not task.done():
                offline = await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=settings.live_speech_offline_grace_seconds,
                )
            elif task.exception() is None:
                offline = task.result()
            else:
                offline = None
        except (asyncio.TimeoutError, asyncio.CancelledError):
            offline = None
        if self._commit_at is not None:
            self._metrics.add(
                "provider.offline_transcript", (monotonic() - self._commit_at) * 1000,
            )
        if offline and offline != chosen:
            chosen = offline
        return chosen

    async def _correct(self, text: str) -> str:
        """Context-aware Cerebras correction; keep text on failure."""
        prompt = self.scope.prompts.get(CORRECTION_PROMPT_KEY, "")
        if not prompt.strip():
            logger.warning("live_speech.correction_prompt_missing")
            return text
        started = monotonic()
        decision = await correct_transcript(
            prompt,
            self._correction_history,
            text,
            timeout=self.scope.correction_timeout,
        )
        self._metrics.add("provider.correction", (monotonic() - started) * 1000)
        if (
            decision is None
            or not decision.changed
            or not decision.corrected_text.strip()
        ):
            return text
        logger.info("live_speech.correction_changed")
        return decision.corrected_text.strip()

    def note_turn(self, role: str, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        self._correction_history.append((role, stripped))
        del self._correction_history[:-6]

    async def _begin_turn(self, item_id: str, text: str) -> None:
        if self._turn_task is not None and not self._turn_task.done():
            await self.cancel_turn(self._turn_id, "new_user_turn")
        turn_id = str(uuid4())
        self._turn_id = turn_id
        self.note_turn("user", text)
        self._turn_cancel = asyncio.Event()
        pending = self._pending_final
        self._pending_final = None
        if pending is not None:
            self._conversation.handle(pending)
        self._conversation.handle(ConversationEvent(kind="ai_think", turn_id=turn_id))
        await self._emit_json(
            {
                "type": "transcript.final",
                "turn_id": turn_id,
                "item_id": item_id,
                "text": text,
                "sequence": self._next_sequence(),
            }
        )
        self._turn_task = asyncio.create_task(self._run_turn(turn_id, text))

    async def _run_turn(self, turn_id: str, text: str) -> None:
        await run_voice_turn(self, turn_id, text)

    def _client_tools(self, turn_id: str) -> Callable[[list[dict]], Awaitable[None]]:
        return voice_tool_callback(self, turn_id)

    async def _on_library_event(self, payload: dict) -> None:
        await forward_library_trace(self.scope, payload, self._emit_json)

    async def _stop_turn_helpers(self, tts_task: asyncio.Task[None]) -> None:
        helpers = [tts_task]
        if self._cues.waiting_task is not None:
            self._cues.cancel_waiting()
            helpers.append(self._cues.waiting_task)
        tts_task.cancel()
        await asyncio.gather(*helpers, return_exceptions=True)

    async def _tts_chunks(self, text: str) -> AsyncIterator[bytes]:
        async for chunk in self._tts.stream(text, language=self.scope.language):
            yield chunk

    def _mark_first_audio(self) -> None:
        if not self._first_audio_logged and self._final_at is not None:
            self._first_audio_logged = True
            self._metrics.add(
                "provider.first_tts_audio", (monotonic() - self._final_at) * 1000,
            )

    def record_client_latency(self, phase: str, milliseconds: float) -> None:
        self._metrics.add(phase, milliseconds)

    async def _await_final(self) -> None:
        try:
            await asyncio.sleep(settings.live_speech_stt_timeout_seconds)
            await self._error("stt_final_timeout", "Transcription did not complete", True)
        except asyncio.CancelledError:
            pass

    async def _state(self, state: str) -> None:
        if state == "speaking":
            self._conversation.handle(
                ConversationEvent(kind="ai_speak", turn_id=self._turn_id),
            )
        await self._emit_json(
            {
                "type": "session.state",
                "state": state,
                "conversation_state": self._conversation.state,
            }
        )

    async def _error(self, code: str, message: str, retryable: bool) -> None:
        await self._emit_json(
            {
                "type": "session.error",
                "code": code,
                "message": message,
                "retryable": retryable,
            }
        )

    def _advance_audio_sequence(self, sequence: int) -> None:
        if sequence <= self._last_audio_sequence:
            self._conversation.handle(ConversationEvent(kind="session_reset"))
            raise ValueError("audio_sequence_out_of_order")
        self._last_audio_sequence = sequence

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence
