"""Tests for attempt-scoped research progress WebSocket fan-out."""

from __future__ import annotations

import asyncio

import pytest
from starlette.websockets import WebSocketState

from app.realtime.research_progress_broadcast import ResearchProgressBroadcastRegistry


class FakeWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class HungWebSocket(FakeWebSocket):
    async def send_json(self, payload: dict) -> None:
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_research_progress_broadcast_delivers_to_subscribed_attempt_only():
    registry = ResearchProgressBroadcastRegistry()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()

    await registry.subscribe("att_a", ws_a)
    await registry.subscribe("att_b", ws_b)

    event = {"type": "research.progress", "attempt_id": "att_a", "sequence": 1}
    await registry.publish("att_a", event)

    assert ws_a.sent == [event]
    assert ws_b.sent == []


@pytest.mark.asyncio
async def test_research_progress_broadcast_drops_hung_socket(monkeypatch):
    monkeypatch.setattr(
        "app.realtime.research_progress_broadcast._SEND_TIMEOUT_SECONDS",
        0.05,
    )
    registry = ResearchProgressBroadcastRegistry()
    hung = HungWebSocket()
    live = FakeWebSocket()
    await registry.subscribe("att_1", hung)
    await registry.publish("att_1", {"sequence": 1})
    await registry.subscribe("att_1", live)
    await registry.publish("att_1", {"sequence": 2})
    assert hung.sent == []
    assert live.sent == [{"sequence": 2}]
