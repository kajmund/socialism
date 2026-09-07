"""In-process fan-out for live expertgranskning Word-review results."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


class ExpertgranskningBroadcastRegistry:
    """Broadcast Word-review events to sockets subscribed by job_id."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._socket_keys: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, job_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(job_id, set()).add(websocket)
            self._socket_keys[websocket] = job_id

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            job_id = self._socket_keys.pop(websocket, None)
            if job_id is None:
                return
            room = self._rooms.get(job_id)
            if room is None:
                return
            room.discard(websocket)
            if not room:
                self._rooms.pop(job_id, None)

    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(job_id, ()))
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
                    "Dropping expertgranskning-watch WS client after send error: %s",
                    exc,
                )
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    await self._drop_socket(ws)

    async def _drop_socket(self, websocket: WebSocket) -> None:
        job_id = self._socket_keys.pop(websocket, None)
        if job_id is None:
            return
        room = self._rooms.get(job_id)
        if room is None:
            return
        room.discard(websocket)
        if not room:
            self._rooms.pop(job_id, None)


expertgranskning_broadcast = ExpertgranskningBroadcastRegistry()
