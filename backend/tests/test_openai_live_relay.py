"""Relay and registry for OpenAI Realtime native audio."""

import time

import pytest
import websockets
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.realtime import openai_live_relay as relay
from app.realtime.openai_live_relay import (
    OpenAILiveRelayRegistry,
    openai_live_relay_registry,
)


def test_registry_is_single_use_and_expires() -> None:
    registry = OpenAILiveRelayRegistry()
    registry.register("s1", "gpt-realtime", time.time() + 60)
    assert registry.take("s1") == "gpt-realtime"
    assert registry.take("s1") is None
    registry.register("s2", "gpt-realtime", time.time() - 1)
    assert registry.take("s2") is None
    assert registry.take("unknown") is None


def _relay_app() -> FastAPI:
    app = FastAPI()
    app.include_router(relay.router)
    return app


def test_relay_bridges_frames_and_rejects_unknown_or_reused_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str] = []

    async def upstream_handler(ws) -> None:
        async for message in ws:
            received.append(str(message))
            await ws.send('{"type": "session.created", "id": "sess-1"}')
            return

    async def fake_connect(model: str, secret: str):
        assert model == "gpt-realtime"
        assert secret == "s1"
        server = await websockets.serve(upstream_handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        return await websockets.connect(f"ws://127.0.0.1:{port}")

    monkeypatch.setattr(relay, "_connect_upstream", fake_connect)
    openai_live_relay_registry.register("s1", "gpt-realtime", time.time() + 60)
    with TestClient(_relay_app()) as client:
        with client.websocket_connect("/ws/openai-live?session=s1") as ws:
            ws.send_text('{"type": "input_audio_buffer.append", "audio": "aGk="}')
            event = ws.receive_json()
            assert event == {"type": "session.created", "id": "sess-1"}
        with client.websocket_connect("/ws/openai-live?session=s1") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == 4401
        with client.websocket_connect("/ws/openai-live?session=unknown") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == 4401
    assert received == ['{"type": "input_audio_buffer.append", "audio": "aGk="}']
