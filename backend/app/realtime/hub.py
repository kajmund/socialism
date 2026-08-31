"""In-process WebSocket fan-out for admin realtime channels."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


def _customer_id_from_event(event: dict[str, Any]) -> int | None:
    """Return the tenant id carried by a push event, if any."""
    event_type = event.get("type")
    if event_type == "job.updated":
        job = event.get("job")
        if isinstance(job, dict):
            cid = job.get("customer_id")
            return cid if isinstance(cid, int) else None
        return None
    if event_type == "report.updated":
        report = event.get("report")
        if isinstance(report, dict):
            cid = report.get("customer_id")
            return cid if isinstance(cid, int) else None
        return None
    if event_type == "report.deleted":
        cid = event.get("customer_id")
        return cid if isinstance(cid, int) else None
    return None


class EventHub:
    """Broadcast JSON events to sockets, optionally scoped by customer_id."""

    def __init__(self, *, name: str) -> None:
        self._name = name
        self._sockets: dict[WebSocket, int | None] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        websocket: WebSocket,
        *,
        customer_id: int | None = None,
    ) -> None:
        async with self._lock:
            self._sockets[websocket] = customer_id

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._sockets.pop(websocket, None)

    def _matches_scope(
        self,
        socket_scope: int | None,
        event_customer_id: int | None,
    ) -> bool:
        if socket_scope is None:
            return True
        return event_customer_id == socket_scope

    async def publish(self, event: dict[str, Any]) -> None:
        event_customer_id = _customer_id_from_event(event)
        async with self._lock:
            targets = list(self._sockets.items())
        if not targets:
            return
        dead: list[WebSocket] = []
        for ws, scope in targets:
            if not self._matches_scope(scope, event_customer_id):
                continue
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
                    self._sockets.pop(ws, None)


# Back-compat alias used by jobs.
JobHub = EventHub

job_hub = EventHub(name="jobs")
report_hub = EventHub(name="reports")
