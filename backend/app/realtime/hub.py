"""In-process WebSocket fan-out for admin realtime channels."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


class EventHub:
    """Broadcast JSON events to all connected sockets on one channel."""

    def __init__(self, *, name: str) -> None:
        self._name = name
        self._sockets: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._sockets.add(websocket)

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._sockets.discard(websocket)

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._sockets)
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
                logger.debug("Dropping %s WS client after send error: %s", self._name, exc)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._sockets.discard(ws)


# Back-compat alias used by jobs.
JobHub = EventHub

job_hub = EventHub(name="jobs")
report_hub = EventHub(name="reports")
