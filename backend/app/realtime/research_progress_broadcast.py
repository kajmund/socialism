"""In-process fan-out for persisted research progress events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


class ResearchProgressBroadcastRegistry:
    """Broadcast research progress to sockets subscribed by attempt_id."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._socket_keys: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, attempt_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(attempt_id, set()).add(websocket)
            self._socket_keys[websocket] = attempt_id

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            await self._drop_socket(websocket)

    async def publish(self, attempt_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(attempt_id, ()))
        if not sockets:
            return
        dead: list[WebSocket] = []
        for ws in sockets:
            if ws.client_state != WebSocketState.CONNECTED:
                dead.append(ws)
                continue
            try:
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError) as exc:
                logger.debug(
                    "Dropping research-progress WS client after send error: %s", exc
                )
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    await self._drop_socket(ws)

    async def _drop_socket(self, websocket: WebSocket) -> None:
        attempt_id = self._socket_keys.pop(websocket, None)
        if attempt_id is None:
            return
        room = self._rooms.get(attempt_id)
        if room is None:
            return
        room.discard(websocket)
        if not room:
            self._rooms.pop(attempt_id, None)


research_progress_broadcast = ResearchProgressBroadcastRegistry()
