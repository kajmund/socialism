"""Provider and canonical-chat orchestration for one Live Speech socket."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from openai import OpenAIError

from app.config import settings
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.schemas.workspace import WorkspaceState
from app.services import jobs as jobs_service
from app.services.elevenlabs_tts import ElevenLabsTts
from app.services.live_speech_admit import admit_voice_turn, current_workspace_state
from app.services.live_speech_coordinator import SpeechResponseCoordinator
from app.services.expert_turn_cancel import bind_turn_cancel
from app.services.live_speech_cues import LiveSpeechCues
from app.services.live_speech_history import persist_interrupted_voice_turn
from app.services.live_speech_progress import bind_tool_progress
from app.services.openai_live_transcription import (
    OpenAITranscriptionStream,
    TranscriptEvent,
)
from app.services.persona_chat import ChatTurnError
from app.services.sme_expert_turns import execute_expert_turn
from app.services.speech_segmenter import (
    SpeechSegmenter,
    VisibleSpeechText,
    strip_voice_tags,
)

EmitJson = Callable[[dict], Awaitable[None]]
EmitAudio = Callable[[bytes], Awaitable[None]]
logger = logging.getLogger(__name__)
_V4_TURBO_MODEL = "eleven_v4_turbo"
_V4_DELIVERY_PROMPT_KEY = "chat.expert.live_speech_delivery"


@dataclass(frozen=True, slots=True)
class LiveSpeechScope:
    user_id: str
    customer_id: int
    workspace_id: str
    expert_id: str
    language: str
    voice_id: str
    workspace_state: WorkspaceState
    prompts: dict[str, str] = field(default_factory=dict)
    recent_turns: tuple[tuple[str, str], ...] = ()


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
        self._stt = OpenAITranscriptionStream(
            api_key=settings.openai_api_key,
            model=settings.live_speech_stt_model,
            language=scope.language,
            on_event=self._on_transcript,
        )
        self._tts = ElevenLabsTts(
            api_key=settings.elevenlabs_api_key,
            voice_id=scope.voice_id,
            model_id=settings.live_speech_tts_model,
            output_format=settings.live_speech_tts_output_format,
        )
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
        self._cues = LiveSpeechCues(self)
        self._coordinator = SpeechResponseCoordinator(
            stream=self._tts_chunks,
            emit_json=self._emit_json,
            emit_audio=self._emit_audio,
            sample_rate=_output_sample_rate(),
            next_sequence=self._next_sequence,
            on_state=self._state,
            on_first_audio=self._mark_first_audio,
        )

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

    async def audio_started(self, sequence: int) -> None:
        self._advance_audio_sequence(sequence)
        self._speech_started_at = monotonic()
        self._commit_at = None
        self._first_partial_logged = False
        self._user_text_partial = ""
        self._cues.restart_listener()

    async def commit_audio(self, sequence: int) -> None:
        self._advance_audio_sequence(sequence)
        self._commit_at = monotonic()
        self._cues.stop_listener()
        self._coordinator.drop_aside()
        await self._stt.commit()
        if self._commit_timeout is not None:
            self._commit_timeout.cancel()
        self._commit_timeout = asyncio.create_task(self._await_final())

    async def cancel_audio(self) -> None:
        await self._stt.clear()
        self._partials.clear()
        await self._state("listening")

    async def set_muted(self, muted: bool) -> None:
        self._muted = muted
        await self._state("paused" if muted else "listening")

    async def cancel_turn(self, turn_id: str | None, reason: str) -> None:
        task = self._turn_task
        if task is None or task.done() or turn_id != self._turn_id:
            return
        cancelled_at = monotonic()
        self._turn_cancel.set()
        self._coordinator.drop_aside()
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
        logger.info(
            "live_speech.turn_cancelled turn_id=%s latency_ms=%.1f",
            turn_id,
            (monotonic() - cancelled_at) * 1000,
        )
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
            return
        if self._commit_timeout is not None:
            self._commit_timeout.cancel()
            self._commit_timeout = None
        text = event.text.strip()
        if not text:
            await self._error("empty_transcript", "No speech was transcribed", True)
            return
        if self._cues.echoes_listener(text):
            return
        self._final_at = monotonic()
        self._first_delta_logged = False
        self._first_audio_logged = False
        if self._commit_at is not None:
            logger.info(
                "live_speech.final_transcript item_id=%s latency_ms=%.1f",
                item_id,
                (self._final_at - self._commit_at) * 1000,
            )
        if self._cues.assistant_active() and await self._cues.classify_user_speech(
            text, final=True
        ):
            return
        await self._begin_turn(item_id, text)

    async def _begin_turn(self, item_id: str, text: str) -> None:
        if self._turn_task is not None and not self._turn_task.done():
            await self.cancel_turn(self._turn_id, "new_user_turn")
        turn_id = str(uuid4())
        self._turn_id = turn_id
        self._turn_cancel = asyncio.Event()
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
        await self._state("thinking")
        request_id = f"voice-{uuid4().hex}"
        self._request_id = request_id
        self._user_text = text
        self._assistant_text = ""
        factory = jobs_service.job_session_factory()
        workspace_state = await current_workspace_state(factory, self.scope)
        turn = await admit_voice_turn(factory, self.scope, request_id, text)
        self._request_fence = turn.fence
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._coordinator.reset_turn()
        tts_task = asyncio.create_task(self._speak(turn_id, queue))
        self._cues.start_waiting(turn_id)
        on_token = self._main_token_handler(turn_id, queue)
        try:
            with (
                bind_tool_progress(self._cues.on_tool_progress),
                bind_turn_cancel(self._turn_cancel),
            ):
                done = await execute_expert_turn(
                    factory,
                    request_id=request_id,
                    persona_id=self.scope.expert_id,
                    message=text,
                    image_sha256=None,
                    fence=turn.fence,
                    token=turn.lease_token,
                    on_token=on_token,
                    workspace_id=self.scope.workspace_id,
                    workspace_state=workspace_state,
                    on_client_tools=self._client_tools(turn_id),
                    extra_system_prompt_key=(
                        _V4_DELIVERY_PROMPT_KEY
                        if settings.live_speech_tts_model == _V4_TURBO_MODEL
                        else None
                    ),
                    assistant_reply_transform=(
                        strip_voice_tags
                        if settings.live_speech_tts_model == _V4_TURBO_MODEL
                        else None
                    ),
                )
            queue.put_nowait(None)
            await self._finish_spoken_turn(turn_id, done.reply, tts_task)
        except asyncio.CancelledError:
            await self._stop_turn_helpers(tts_task)
            raise
        except (ChatTurnError, ElevenLabsApiError, OpenAIError, RuntimeError, TimeoutError):
            await self._stop_turn_helpers(tts_task)
            await self._error("chat_turn_failed", "Expert turn failed", True)

    def _main_token_handler(
        self,
        turn_id: str,
        queue: asyncio.Queue[str | None],
    ) -> Callable[[str], Awaitable[None]]:
        visible_text = VisibleSpeechText()

        async def on_token(delta: str) -> None:
            if not self._first_delta_logged and self._final_at is not None:
                self._first_delta_logged = True
                self._coordinator.note_main_text()
                logger.info(
                    "live_speech.first_llm_delta turn_id=%s latency_ms=%.1f",
                    turn_id,
                    (monotonic() - self._final_at) * 1000,
                )
            display_delta = visible_text.push(delta)
            self._assistant_text += display_delta
            if display_delta:
                await self._emit_json(
                    {
                        "type": "assistant.text.delta",
                        "turn_id": turn_id,
                        "sequence": self._next_sequence(),
                        "text": display_delta,
                    }
                )
            queue.put_nowait(delta)

        return on_token

    async def _finish_spoken_turn(
        self,
        turn_id: str,
        reply: str,
        tts_task: asyncio.Task[None],
    ) -> None:
        try:
            await tts_task
            self._coordinator.allow_progress()
        except ElevenLabsApiError:
            await self._emit_final_text(turn_id, reply)
            await self._error("tts_failed", "Speech synthesis failed", True)
            await self._state("listening")
            return
        await self._emit_final_text(turn_id, reply)
        self._cues.cancel_waiting()
        await self._state("listening")

    async def _emit_final_text(self, turn_id: str, reply: str) -> None:
        await self._emit_json(
            {
                "type": "assistant.text.final",
                "turn_id": turn_id,
                "text": reply,
                "interrupted": False,
            }
        )

    async def _speak(self, turn_id: str, queue: asyncio.Queue[str | None]) -> None:
        segmenter = SpeechSegmenter()
        while True:
            delta = await queue.get()
            segments = segmenter.finish() if delta is None else segmenter.push(delta)
            for segment in segments:
                await self._coordinator.play_main(segment, turn_id)
                self._spoken_text = self._coordinator.spoken_text
            if delta is None:
                return

    def _client_tools(self, turn_id: str) -> Callable[[list[dict]], Awaitable[None]]:
        async def emit(calls: list[dict]) -> None:
            for call in calls:
                await self._emit_json({"type": "workspace.tool", "turn_id": turn_id, **call})

        return emit

    async def _on_library_event(self, payload: dict) -> None:
        await self._forward_model_trace(payload)

    async def _play_reply(self, text: str) -> None:
        self._voiced_reply = text
        await self._state("speaking")
        await self._coordinator.play_main(text, self._turn_id or "followup")
        if not self._closed:
            await self._state("listening")

    async def _forward_model_trace(self, payload: dict) -> None:
        if payload.get("type") != "model_trace":
            return
        if payload.get("thread_id") != self.scope.expert_id:
            return
        workspace_id = payload.get("workspace_id")
        if workspace_id not in (None, self.scope.workspace_id):
            return
        target = payload.get("target_user_id")
        if target not in (None, self.scope.user_id):
            return
        await self._emit_json(payload)

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
            logger.info(
                "live_speech.first_tts_audio turn_id=%s latency_ms=%.1f",
                self._turn_id,
                (monotonic() - self._final_at) * 1000,
            )

    async def _await_final(self) -> None:
        try:
            await asyncio.sleep(settings.live_speech_stt_timeout_seconds)
            await self._error("stt_final_timeout", "Transcription did not complete", True)
        except asyncio.CancelledError:
            pass

    async def _state(self, state: str) -> None:
        await self._emit_json({"type": "session.state", "state": state})

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
            raise ValueError("audio_sequence_out_of_order")
        self._last_audio_sequence = sequence

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence


def _output_sample_rate() -> int:
    with suppress(ValueError):
        return int(settings.live_speech_tts_output_format.rsplit("_", 1)[1])
    raise RuntimeError("LIVE_SPEECH_TTS_OUTPUT_FORMAT must include a sample rate")
