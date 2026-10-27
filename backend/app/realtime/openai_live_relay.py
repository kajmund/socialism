"""WebSocket relay for OpenAI Realtime native audio.

Browsers cannot send the Authorization header a Realtime WebSocket requires,
so the backend mints an ephemeral client secret and relays the browser's
frames to OpenAI with the secret as the bearer token. The secret appears only
in the minted session URL, is single-use, and expires with the minted TTL.
"""

from __future__ import annotations

import asyncio
import logging
import time

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class OpenAILiveRelayRegistry:
    """Single-use client secrets: secret -> (model, expires_at)."""

    def __init__(self) -> None:
        self._secrets: dict[str, tuple[str, float]] = {}

    def register(self, secret: str, model: str, expires_at: float) -> None:
        now = time.time()
        for key in [key for key, expiry in self._secrets.items() if expiry[1] <= now]:
            del self._secrets[key]
        self._secrets[secret] = (model, expires_at)

    def take(self, secret: str) -> str | None:
        entry = self._secrets.pop(secret, None)
        if entry is None:
            return None
        model, expires_at = entry
        return model if expires_at > time.time() else None


openai_live_relay_registry = OpenAILiveRelayRegistry()


async def _connect_upstream(model: str, secret: str):
    url = (
        f"{settings.openai_websocket_base_url.rstrip('/')}/v1/realtime"
        f"?model={model}"
    )
    return await websockets.connect(
        url,
        additional_headers={"Authorization": f"Bearer {secret}"},
        open_timeout=10,
    )


@router.websocket("/ws/openai-live")
async def openai_live_relay(websocket: WebSocket) -> None:
    secret = websocket.query_params.get("session")
    model = openai_live_relay_registry.take(secret) if secret else None
    await websocket.accept()
    if model is None:
        await websocket.close(code=4401)
        return
    try:
        upstream = await _connect_upstream(model, secret)
    except Exception:
        logger.exception("openai_live_relay.upstream_connect_failed")
        await websocket.close(code=1011)
        return
    try:
        await asyncio.gather(
            _browser_to_upstream(websocket, upstream),
            _upstream_to_browser(websocket, upstream),
        )
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass
    finally:
        await upstream.close()


async def _browser_to_upstream(websocket: WebSocket, upstream) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("bytes") is not None:
            await upstream.send(message["bytes"])
        elif message.get("text") is not None:
            await upstream.send(message["text"])


async def _upstream_to_browser(websocket: WebSocket, upstream) -> None:
    async for message in upstream:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_text(message)
