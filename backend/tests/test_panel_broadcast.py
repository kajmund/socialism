"""Tests for live panel session WebSocket broadcast registry."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketState

from app.realtime.panel_broadcast import PanelBroadcastRegistry


class FakeWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_panel_broadcast_delivers_to_subscribed_socket_only():
    registry = PanelBroadcastRegistry()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()

    await registry.subscribe("panel_abc", ws_a)
    await registry.subscribe("panel_xyz", ws_b)

    event = {
        "type": "turn.completed",
        "session_id": "panel_abc",
        "turn": {"turn_id": "turn_1", "speaker": "Spinndoktor", "phase": "opening", "content": "Hej"},
    }
    await registry.publish("panel_abc", event)

    assert ws_a.sent == [event]
    assert ws_b.sent == []


@pytest.mark.asyncio
async def test_panel_broadcast_unsubscribe_on_disconnect():
    registry = PanelBroadcastRegistry()
    ws = FakeWebSocket()
    await registry.subscribe("panel_42", ws)
    await registry.unsubscribe(ws)

    await registry.publish("panel_42", {"type": "panel.finished", "session_id": "panel_42", "status": "succeeded"})
    assert ws.sent == []
