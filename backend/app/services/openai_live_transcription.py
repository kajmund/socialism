"""OpenAI Realtime transcription with application-owned turn detection."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from websockets.exceptions import ConnectionClosedError

from app.config import settings

logger = logging.getLogger(__name__)
_KEYWORD_LIMIT = 24

TranscriptCallback = Callable[["TranscriptEvent"], Awaitable[None]]


def clean_keywords(keywords: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        text = " ".join(keyword.replace("<", " ").replace(">", " ").split())
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text[:48])
        if len(cleaned) >= _KEYWORD_LIMIT:
            break
    return cleaned


def transcription_session(
    *,
    model: str,
    language: str,
    prompt: str,
    keywords: list[str],
    noise_reduction: str,
) -> dict[str, Any]:
    transcription: dict[str, Any] = {
        "model": model,
        "languages": [language],
        "delay": "low",
    }
    if prompt.strip():
        transcription["prompt"] = prompt.strip()
    terms = clean_keywords(keywords)
    if terms:
        transcription["keywords"] = terms
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "noise_reduction": {"type": noise_reduction},
                    "transcription": transcription,
                    "turn_detection": None,
                }
            },
        },
    }


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    kind: str
    item_id: str | None = None
    text: str = ""
    code: str | None = None


def parse_transcription_event(raw: dict[str, Any]) -> TranscriptEvent | None:
    event_type = raw.get("type")
    if event_type == "conversation.item.input_audio_transcription.delta":
        return TranscriptEvent(
            kind="partial",
            item_id=_optional_string(raw.get("item_id")),
            text=_required_string(raw.get("delta"), "delta"),
        )
    if event_type == "conversation.item.input_audio_transcription.completed":
        return TranscriptEvent(
            kind="final",
            item_id=_required_string(raw.get("item_id"), "item_id"),
            text=_required_string(raw.get("transcript"), "transcript").strip(),
        )
    if event_type in {
        "conversation.item.input_audio_transcription.failed",
        "error",
    }:
        error = raw.get("error")
        detail = error if isinstance(error, dict) else raw
        return TranscriptEvent(
            kind="error",
            item_id=_optional_string(raw.get("item_id")),
            text=_optional_string(detail.get("message")) or "Transcription failed",
            code=_optional_string(detail.get("code")) or "stt_provider_error",
        )
    return None


class OpenAITranscriptionStream:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        language: str,
        on_event: TranscriptCallback,
        prompt: str = "",
        keywords: list[str] | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._language = language
        self._prompt = prompt
        self._keywords = list(keywords or [])
        self._on_event = on_event
        self._sent = ""
        self._manager: AbstractAsyncContextManager[Any] | None = None
        self._connection: Any = None
        self._reader: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._manager = self._client.realtime.connect(
            extra_query={"intent": "transcription"},
            max_retries=0,
        )
        self._connection = await self._manager.__aenter__()
        await self._send_session()
        self._reader = asyncio.create_task(self._read_events())

    async def update(self, *, prompt: str | None = None, keywords: list[str] | None = None) -> None:
        if prompt is not None:
            self._prompt = prompt
        if keywords is not None:
            self._keywords = list(keywords)
        if self._connection is not None:
            await self._send_session()

    async def _send_session(self) -> None:
        payload = transcription_session(
            model=self._model,
            language=self._language,
            prompt=self._prompt,
            keywords=self._keywords,
            noise_reduction=settings.live_speech_noise_reduction,
        )
        encoded = str(payload)
        if encoded == self._sent:
            return
        self._sent = encoded
        await self._connection.send(payload)

    async def append(self, pcm: bytes) -> None:
        await self._connection.send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            }
        )

    async def commit(self) -> None:
        await self._connection.send({"type": "input_audio_buffer.commit"})

    async def clear(self) -> None:
        await self._connection.send({"type": "input_audio_buffer.clear"})

    async def close(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        manager = self._manager
        self._manager = None
        if manager is not None:
            await manager.__aexit__(None, None, None)
        await self._client.close()

    async def _read_events(self) -> None:
        try:
            async for event in self._connection:
                raw = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
                if not isinstance(raw, dict):
                    continue
                parsed = parse_transcription_event(raw)
                if parsed is None:
                    continue
                try:
                    await self._on_event(parsed)
                except Exception:
                    logger.exception("transcription event handler failed")
        except ConnectionClosedError:
            await self._on_event(
                TranscriptEvent(
                    kind="error",
                    text="Transcription connection closed",
                    code="stt_connection_closed",
                )
            )


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"OpenAI transcription event missing {name}")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
