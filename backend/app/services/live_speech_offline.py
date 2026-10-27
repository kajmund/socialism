"""Second-pass offline transcription for committed live-speech audio.

The streaming Realtime transcription drives preview and barge-in. This pass
re-transcribes the committed utterance with the configured offline model; the
live-speech runtime prefers its result for the canonical turn text when it
lands within the grace window. It is an accuracy enhancement, not a fallback
path: on timeout or provider error the streaming text is used unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import struct

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

PCM_SAMPLE_RATE = 24000
_BYTES_PER_SAMPLE = 2
MAX_UTTERANCE_BYTES = PCM_SAMPLE_RATE * _BYTES_PER_SAMPLE * 60  # 60 s of PCM16


def pcm_to_wav(pcm: bytes, *, sample_rate: int = PCM_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a minimal WAV container."""
    data_len = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_len,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * _BYTES_PER_SAMPLE,
        _BYTES_PER_SAMPLE,
        16,
        b"data",
        data_len,
    )
    return header + pcm


class OfflineTranscriber:
    """One AsyncOpenAI client per live-speech session, closed with the session."""

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    @property
    def enabled(self) -> bool:
        return settings.live_speech_two_pass_enabled and bool(settings.openai_api_key)

    async def transcribe(self, pcm: bytes, language: str) -> str | None:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        model = settings.live_speech_offline_stt_model or settings.live_speech_stt_model
        try:
            transcript = await asyncio.wait_for(
                self._client.audio.transcriptions.create(
                    model=model,
                    file=("utterance.wav", pcm_to_wav(pcm), "audio/wav"),
                    language=language,
                ),
                timeout=settings.live_speech_offline_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("live_speech.offline_transcript_timeout")
            return None
        except Exception:
            # The streaming pass remains the canonical text when the
            # enhancement fails; the session must not break on this path.
            logger.exception("live_speech.offline_transcript_failed")
            return None
        text = transcript.text.strip()
        return text or None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
