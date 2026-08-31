"""In-process fan-out for live panel session transcripts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


class PanelBroadcastRegistry:
    """Broadcast panel events to sockets subscribed by session_id."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._socket_keys: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(session_id, set()).add(websocket)
            self._socket_keys[websocket] = session_id

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            session_id = self._socket_keys.pop(websocket, None)
            if session_id is None:
                return
            room = self._rooms.get(session_id)
            if room is None:
                return
            room.discard(websocket)
            if not room:
                self._rooms.pop(session_id, None)

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(session_id, ()))
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
                logger.debug("Dropping panel-watch WS client after send error: %s", exc)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    await self._drop_socket(ws)

    async def _drop_socket(self, websocket: WebSocket) -> None:
        session_id = self._socket_keys.pop(websocket, None)
        if session_id is None:
            return
        room = self._rooms.get(session_id)
        if room is None:
            return
        room.discard(websocket)
        if not room:
            self._rooms.pop(session_id, None)


panel_broadcast = PanelBroadcastRegistry()
