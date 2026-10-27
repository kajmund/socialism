"""One active TTS stream for main replies and ephemeral asides."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from time import monotonic

from app.config import settings
from app.services.live_speech_pcm import frame_pcm
from app.services.speech_segmenter import strip_voice_tags

logger = logging.getLogger(__name__)

EmitJson = Callable[[dict], Awaitable[None]]
EmitAudio = Callable[[bytes], Awaitable[None]]
StreamTts = Callable[[str], AsyncIterator[bytes]]


class SpeechResponseCoordinator:
    def __init__(
        self,
        *,
        stream: StreamTts,
        emit_json: EmitJson,
        emit_audio: EmitAudio,
        sample_rate: int,
        next_sequence: Callable[[], int],
        on_state: Callable[[str], Awaitable[None]] | None = None,
        on_first_audio: Callable[[], None] | None = None,
    ) -> None:
        self._stream = stream
        self._emit_json = emit_json
        self._emit_audio = emit_audio
        self._sample_rate = sample_rate
        self._next_sequence = next_sequence
        self._on_state = on_state
        self._on_first_audio = on_first_audio
        self._lock = asyncio.Lock()
        self._aside_token = 0
        self._playback_token = 0
        self._generation = 0
        self._main_generation: int | None = None
        self.main_text_seen = False
        self.spoken_text = ""
        self.spoken_asides: list[str] = []

    def reset_turn(self) -> None:
        self.drop_aside()
        self._main_generation = None
        self.main_text_seen = False
        self.spoken_text = ""

    def note_main_text(self) -> None:
        self.main_text_seen = True
        self.drop_aside()

    def drop_aside(self) -> None:
        self._aside_token += 1

    def interrupt_playback(self) -> None:
        self._aside_token += 1
        self._playback_token += 1
        self._main_generation = None
        self._generation += 1

    def _next_generation(self) -> int:
        self._generation += 1
        return self._generation

    def allow_progress(self) -> None:
        self.main_text_seen = False

    async def play_aside(self, text: str, turn_id: str) -> None:
        cleaned = text.strip()
        if not cleaned or self.main_text_seen:
            return
        token = self._aside_token
        generation = self._next_generation()
        async with self._lock:
            if self.main_text_seen or token != self._aside_token:
                return
            await self._play(
                cleaned, turn_id, announce=False, token=token, generation=generation,
            )
            if token == self._aside_token and not self.main_text_seen:
                self.spoken_asides.append(cleaned)

    async def play_main(self, text: str, turn_id: str) -> None:
        self.note_main_text()
        cleaned = text.strip()
        if not cleaned:
            return
        token = self._playback_token
        if self._main_generation is None:
            self._main_generation = self._next_generation()
        generation = self._main_generation
        async with self._lock:
            if token != self._playback_token:
                return
            await self._play(
                cleaned, turn_id, announce=True, token=token, generation=generation,
            )
            if token != self._playback_token:
                return
            spoken = strip_voice_tags(cleaned)
            self.spoken_text = f"{self.spoken_text} {spoken}".strip() if self.spoken_text else spoken

    async def _play(
        self,
        text: str,
        turn_id: str,
        *,
        announce: bool,
        token: int,
        generation: int,
    ) -> None:
        if announce and self._on_state is not None:
            await self._on_state("speaking")
        started_at = monotonic()
        audio_bytes = 0
        await self._emit_json(self._audio_event("audio.output.start", turn_id, generation))
        try:
            iterator = self._stream(text).__aiter__()
            while True:
                # The timeout bounds one provider wait, not the whole reply:
                # playback is paced to real time inside this loop, so a total
                # cap would cut every answer longer than the timeout.
                try:
                    async with asyncio.timeout(settings.live_speech_tts_timeout_seconds):
                        chunk = await iterator.__anext__()
                except StopAsyncIteration:
                    break
                if self._token_cancelled(announce, token):
                    await self._emit_json(
                        self._audio_event("audio.output.end", turn_id, generation)
                    )
                    return
                if self._on_first_audio is not None:
                    self._on_first_audio()
                audio_bytes += len(chunk)
                duration = audio_bytes / (self._sample_rate * 2)
                lead = duration - (monotonic() - started_at)
                if lead > 0.4:
                    await asyncio.sleep(lead - 0.4)
                await self._emit_audio(frame_pcm(generation, chunk))
        except TimeoutError:
            logger.warning("live_speech.tts_timeout generation=%s turn_id=%s", generation, turn_id)
            await self._emit_json(self._audio_event("audio.output.end", turn_id, generation))
            raise
        await self._emit_json(self._audio_event("audio.output.end", turn_id, generation))

    def _token_cancelled(self, announce: bool, token: int) -> bool:
        return (announce and token != self._playback_token) or (
            not announce and token != self._aside_token
        )

    def _audio_event(self, event_type: str, turn_id: str, generation: int) -> dict:
        return {
            "type": event_type,
            "turn_id": turn_id,
            "response_id": turn_id,
            "generation_id": generation,
            "sequence": self._next_sequence(),
            **(
                {"codec": "pcm16", "sample_rate": self._sample_rate}
                if event_type.endswith(".start")
                else {}
            ),
        }
