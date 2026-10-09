"""OpenAI Realtime transcription with application-owned turn detection."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from websockets.exceptions import ConnectionClosedError

TranscriptCallback = Callable[["TranscriptEvent"], Awaitable[None]]


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
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._language = language
        self._on_event = on_event
        self._manager: AbstractAsyncContextManager[Any] | None = None
        self._connection: Any = None
        self._reader: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._manager = self._client.realtime.connect(
            extra_query={"intent": "transcription"},
            max_retries=0,
        )
        self._connection = await self._manager.__aenter__()
        await self._connection.send(
            {
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {
                                "model": self._model,
                                "languages": [self._language],
                                "delay": "low",
                            },
                            "turn_detection": None,
                        }
                    },
                },
            }
        )
        self._reader = asyncio.create_task(self._read_events())

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
                if parsed is not None:
                    await self._on_event(parsed)
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
