"""Tests for live Word-review WebSocket broadcast registry."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketState

from app.realtime.expertgranskning_broadcast import ExpertgranskningBroadcastRegistry


class FakeWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_expertgranskning_broadcast_delivers_to_subscribed_socket_only():
    registry = ExpertgranskningBroadcastRegistry()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()

    await registry.subscribe("job_abc", ws_a)
    await registry.subscribe("job_xyz", ws_b)

    event = {
        "type": "expertgranskning.action.created",
        "job_id": "job_abc",
        "action": {"id": "wa_1"},
    }
    await registry.publish("job_abc", event)

    assert ws_a.sent == [event]
    assert ws_b.sent == []


@pytest.mark.asyncio
async def test_expertgranskning_broadcast_unsubscribe_on_disconnect():
    registry = ExpertgranskningBroadcastRegistry()
    ws = FakeWebSocket()
    await registry.subscribe("job_42", ws)
    await registry.unsubscribe(ws)

    await registry.publish(
        "job_42",
        {"type": "expertgranskning.finished", "job_id": "job_42", "status": "succeeded"},
    )
    assert ws.sent == []
