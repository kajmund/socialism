"""Integration coverage for the SME quick-acknowledgment handover.

The fast model writes a short acknowledgment before the main prompt is sent.
The acknowledgment is forwarded into the main turn as an assistant line the
expert has already said, then sent to the user right away. The full reply
streams after it: no error events, no acknowledgment tokens after ``done``,
and the persisted reply is exactly the full answer.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.config import settings
from app.llm import set_text_streamer
from tests.test_websocket import (
    _bolag_token,
    _enable_sme_expert,
    ws_client as ws_client,
)


def _send_payload(request_id: str, persona_id: str, message: str) -> dict:
    return {
        "type": "send",
        "request_id": request_id,
        "thread_type": "expert",
        "thread_id": persona_id,
        "message": message,
    }


def _receive_acknowledgment(websocket) -> dict:
    """First non-trace event after typing must be the acknowledgment."""
    while True:
        event = websocket.receive_json()
        if event["type"] == "model_trace":
            continue
        return event


def _drain_until_done(
    websocket,
    *,
    allow_draft: bool,
) -> tuple[list[str], list[str], dict]:
    tokens: list[str] = []
    drafts: list[str] = []
    done = None
    while True:
        event = websocket.receive_json()
        if event["type"] == "token":
            tokens.append(event["text"])
        elif event["type"] == "done":
            done = event
            break
        elif event["type"] == "error":
            pytest.fail(f"acknowledgment handover produced an error: {event['detail']}")
        elif event["type"] == "draft_token":
            assert allow_draft, "acknowledgment token arrived while none was expected"
            drafts.append(event["text"])
    return tokens, drafts, done


def test_sme_websocket_acknowledgment_inserted_before_main_reply(ws_client, monkeypatch):
    client, _loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    release_main = threading.Event()
    seen_messages: dict = {}

    async def fake_ack(factory, *, persona_id, message):
        return "Ok, jag kollar."

    monkeypatch.setattr("app.api.sme_ws.complete_quick_draft", fake_ack)

    async def main_stream(messages):
        seen_messages["last"] = messages[-1] if messages else None
        seen_messages["before_last"] = messages[-2] if len(messages) > 1 else None
        await asyncio.get_running_loop().run_in_executor(None, release_main.wait)
        yield "Fullständigt"
        yield " svar."

    set_text_streamer(main_stream)

    request_id = "quick-draft-inserted"
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(_send_payload(request_id, persona_id, "Fråga med långt svar"))
        assert websocket.receive_json()["type"] == "typing"

        ack = _receive_acknowledgment(websocket)
        assert ack["type"] == "draft_token"
        assert ack["text"] == "Ok, jag kollar."
        assert ack["request_id"] == request_id

        release_main.set()

        tokens, drafts, done = _drain_until_done(websocket, allow_draft=False)
        assert drafts == []
        assert tokens == ["Fullständigt", " svar."]
        assert done is not None
        assert done["reply"] == "Fullständigt svar."
        assert done["messages"][-1]["content"] == "Fullständigt svar."
        assert websocket.receive_json()["type"] == "suggestions"
        assert websocket.receive_json()["type"] == "typing"

    # The main model saw the acknowledgment as an assistant line after the user.
    assert seen_messages["before_last"] == {"role": "user", "content": "Fråga med långt svar"}
    assert seen_messages["last"] == {"role": "assistant", "content": "Ok, jag kollar."}


def test_sme_websocket_missing_acknowledgment_skips_prefill(ws_client, monkeypatch):
    client, _loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    seen_messages: dict = {}

    async def fake_ack(factory, *, persona_id, message):
        return None

    monkeypatch.setattr("app.api.sme_ws.complete_quick_draft", fake_ack)

    async def main_stream(messages):
        seen_messages["last"] = messages[-1] if messages else None
        yield "Riktigt"
        yield " svar."

    set_text_streamer(main_stream)

    request_id = "quick-draft-missing"
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(_send_payload(request_id, persona_id, "Kort fråga"))
        assert websocket.receive_json()["type"] == "typing"
        tokens, drafts, done = _drain_until_done(websocket, allow_draft=False)
        assert drafts == []
        assert tokens == ["Riktigt", " svar."]
        assert done is not None
        assert done["reply"] == "Riktigt svar."

    # No acknowledgment was forwarded: the last message is the user question.
    assert seen_messages["last"] == {"role": "user", "content": "Kort fråga"}


def test_sme_websocket_acknowledgment_disabled(ws_client, monkeypatch):
    client, _loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    called = threading.Event()

    async def fake_ack(factory, *, persona_id, message):
        called.set()
        return "Ok."

    monkeypatch.setattr("app.api.sme_ws.complete_quick_draft", fake_ack)
    monkeypatch.setattr(settings, "sme_quick_draft_enabled", False)

    async def main_stream(_messages):
        yield "Bara"
        yield " riktigt."

    set_text_streamer(main_stream)

    request_id = "quick-draft-disabled"
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(_send_payload(request_id, persona_id, "Fråga utan utkast"))
        assert websocket.receive_json()["type"] == "typing"
        tokens, _drafts, done = _drain_until_done(websocket, allow_draft=False)
        assert tokens == ["Bara", " riktigt."]
        assert done is not None
        assert done["reply"] == "Bara riktigt."
    assert not called.is_set()


def test_sme_websocket_progress_when_main_reply_is_late(ws_client, monkeypatch):
    client, _loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    release_main = threading.Event()
    progress_seen: dict = {}

    monkeypatch.setattr(settings, "sme_quick_progress_delay_seconds", 0.2)

    async def fake_ack(factory, *, persona_id, message):
        return "Ok, jag kollar."

    async def fake_progress(factory, *, persona_id, message, said):
        progress_seen["said"] = said
        return "…jag arbetar fortfarande med avtalet, snart klar."

    monkeypatch.setattr("app.api.sme_ws.complete_quick_draft", fake_ack)
    monkeypatch.setattr("app.api.sme_ws.complete_quick_progress", fake_progress)

    async def main_stream(_messages):
        await asyncio.get_running_loop().run_in_executor(None, release_main.wait)
        yield "Fullständigt"
        yield " svar."

    set_text_streamer(main_stream)

    request_id = "quick-progress-late"
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(_send_payload(request_id, persona_id, "Kommentera avtalet"))
        assert websocket.receive_json()["type"] == "typing"

        ack = _receive_acknowledgment(websocket)
        assert ack["type"] == "draft_token"
        assert ack["text"] == "Ok, jag kollar."

        # The full reply is still running; the progress line arrives on its own.
        while True:
            progress_event = websocket.receive_json()
            if progress_event["type"] == "model_trace":
                continue
            break
        assert progress_event["type"] == "draft_token"
        assert progress_event["text"] == " …jag arbetar fortfarande med avtalet, snart klar."

        release_main.set()

        tokens, drafts, done = _drain_until_done(websocket, allow_draft=False)
        assert drafts == []
        assert tokens == ["Fullständigt", " svar."]
        assert done is not None
        assert done["reply"] == "Fullständigt svar."
        assert websocket.receive_json()["type"] == "suggestions"
        assert websocket.receive_json()["type"] == "typing"

    # The progress line continues the acknowledgment the expert already wrote.
    assert progress_seen["said"] == "Ok, jag kollar."


def test_sme_websocket_no_progress_when_main_reply_is_quick(ws_client, monkeypatch):
    client, _loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    progress_called = threading.Event()

    monkeypatch.setattr(settings, "sme_quick_progress_delay_seconds", 0.5)

    async def fake_ack(factory, *, persona_id, message):
        return "Ok."

    async def fake_progress(factory, *, persona_id, message, said):
        progress_called.set()
        return "…"

    monkeypatch.setattr("app.api.sme_ws.complete_quick_draft", fake_ack)
    monkeypatch.setattr("app.api.sme_ws.complete_quick_progress", fake_progress)

    async def main_stream(_messages):
        yield "Snabbt"
        yield " svar."

    set_text_streamer(main_stream)

    request_id = "quick-progress-fast"
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(_send_payload(request_id, persona_id, "Kort fråga"))
        assert websocket.receive_json()["type"] == "typing"

        ack = _receive_acknowledgment(websocket)
        assert ack["type"] == "draft_token"
        assert ack["text"] == "Ok."

        tokens, drafts, done = _drain_until_done(websocket, allow_draft=False)
        assert drafts == []
        assert tokens == ["Snabbt", " svar."]
        assert done is not None
        assert done["reply"] == "Snabbt svar."
    assert not progress_called.is_set()
