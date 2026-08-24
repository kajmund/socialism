"""Tests for live run activity WebSocket broadcast registry."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketState

from app.realtime.run_broadcast import RunBroadcastRegistry


class FakeWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_run_broadcast_delivers_to_subscribed_socket_only():
    registry = RunBroadcastRegistry()
    key_main = (1, "main")
    key_a = (1, "a")
    ws_main = FakeWebSocket()
    ws_a = FakeWebSocket()

    await registry.subscribe(key_main, ws_main)
    await registry.subscribe(key_a, ws_a)

    event = {
        "type": "round.activity",
        "run_id": 1,
        "variant_id": "main",
        "tick_index": 0,
        "round_index": 0,
        "items": [],
    }
    await registry.publish(key_main, event)

    assert ws_main.sent == [event]
    assert ws_a.sent == []


@pytest.mark.asyncio
async def test_run_broadcast_unsubscribe_on_disconnect():
    registry = RunBroadcastRegistry()
    key = (42, "b")
    ws = FakeWebSocket()
    await registry.subscribe(key, ws)
    await registry.unsubscribe(ws)

    await registry.publish(key, {"type": "tick.started", "run_id": 42, "variant_id": "b"})
    assert ws.sent == []
