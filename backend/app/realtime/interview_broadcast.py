"""In-process fan-out for run-interview transcript updates."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)

InterviewKey = tuple[str, int, str, str, int]


def interview_key_tuple(
    *,
    persona_id: str,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    through_tick_index: int,
) -> InterviewKey:
    return (persona_id, run_id, attempt_id, variant_id, through_tick_index)


class InterviewBroadcastRegistry:
    """Broadcast new interview messages to sockets subscribed by interview key."""

    def __init__(self) -> None:
        self._rooms: dict[InterviewKey, set[WebSocket]] = {}
        self._socket_keys: dict[WebSocket, InterviewKey] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, key: InterviewKey, websocket: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(key, set()).add(websocket)
            self._socket_keys[websocket] = key

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            key = self._socket_keys.pop(websocket, None)
            if key is None:
                return
            room = self._rooms.get(key)
            if room is None:
                return
            room.discard(websocket)
            if not room:
                self._rooms.pop(key, None)

    async def publish(self, key: InterviewKey, message: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(key, ()))
        if not sockets:
            return
        event = {"type": "interview.message", "message": message}
        dead: list[WebSocket] = []
        for ws in sockets:
            if ws.client_state != WebSocketState.CONNECTED:
                dead.append(ws)
                continue
            try:
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError) as exc:
                logger.debug("Dropping interview WS client after send error: %s", exc)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    await self._drop_socket(ws)

    async def _drop_socket(self, websocket: WebSocket) -> None:
        key = self._socket_keys.pop(websocket, None)
        if key is None:
            return
        room = self._rooms.get(key)
        if room is None:
            return
        room.discard(websocket)
        if not room:
            self._rooms.pop(key, None)


interview_broadcast = InterviewBroadcastRegistry()
