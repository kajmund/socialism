import asyncio

import pytest

from app.services.workspace_tool_delivery import (
    WorkspaceToolDelivery,
    voice_tool_callback,
)


def _emitter(events: list[dict]):
    async def emit(payload: dict) -> None:
        events.append(payload)

    return emit


@pytest.mark.asyncio
async def test_delivery_emits_each_call_once_with_turn_and_envelope():
    events: list[dict] = []
    delivery = WorkspaceToolDelivery(
        _emitter(events),
        event_type="workspace_tool",
        turn_id="turn-1",
        envelope={"thread_id": "expert"},
    )
    await delivery.deliver(
        [
            {"name": "show_document", "arguments": {"source_id": "a"}},
            {"name": "show_document", "arguments": {"source_id": "a"}},
            {
                "name": "show_document_set",
                "arguments": {"title": "T", "source_ids": ["a", "b"]},
            },
        ]
    )

    assert [event["name"] for event in events] == ["show_document", "show_document_set"]
    assert all(event["type"] == "workspace_tool" for event in events)
    assert all(event["turn_id"] == "turn-1" for event in events)
    assert all(event["thread_id"] == "expert" for event in events)


@pytest.mark.asyncio
async def test_delivery_stops_when_the_turn_is_no_longer_current():
    events: list[dict] = []
    current = {"value": True}
    delivery = WorkspaceToolDelivery(
        _emitter(events),
        turn_id="turn-1",
        current=lambda: current["value"],
    )
    await delivery.deliver([{"name": "show_document", "arguments": {"source_id": "a"}}])
    current["value"] = False
    await delivery.deliver([{"name": "focus_anchor", "arguments": {"source_id": "b"}}])

    assert [event["arguments"]["source_id"] for event in events] == ["a"]


@pytest.mark.asyncio
async def test_focus_anchor_carries_the_speaking_expert():
    events: list[dict] = []
    delivery = WorkspaceToolDelivery(
        _emitter(events),
        turn_id="turn-1",
        expert_id="expert-a",
    )
    await delivery.deliver(
        [{"name": "focus_anchor", "arguments": {"source_id": "a", "quote": "q"}}]
    )

    assert events[0]["arguments"]["expert_id"] == "expert-a"


@pytest.mark.asyncio
async def test_voice_callback_checks_the_turn_that_owns_the_socket():
    class Runtime:
        _turn_id = "turn-1"

        def __init__(self) -> None:
            self._turn_cancel = asyncio.Event()
            self.events: list[dict] = []

            async def emit(payload: dict) -> None:
                self.events.append(payload)

            self._emit_json = emit

    runtime = Runtime()
    callback = voice_tool_callback(runtime, "turn-1")
    await callback([{"name": "show_document", "arguments": {"source_id": "a"}}])
    runtime._turn_cancel.set()
    await callback([{"name": "show_document", "arguments": {"source_id": "b"}}])

    assert [event["arguments"]["source_id"] for event in runtime.events] == ["a"]
    assert runtime.events[0]["turn_id"] == "turn-1"
