"""Capture the real transport adapter seams with in-memory emitters."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from functools import partial
from typing import Literal

from app.api.sme_ws import _send_workspace_tools
from app.services.live_speech_runtime import LiveSpeechRuntime
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime
from scripts.channel_parity_experiment.types import Capture, Channel
from scripts.document_presentation_benchmark.types import GoldCase

TURN_ID = "deterministic-turn"
EXPERT_ID = "expert-a"


def presentation_call(case: GoldCase) -> dict | None:
    """Return the deterministic decision shared by all adapters."""
    result = deterministic_find_result(case)
    if not case.expected_gallery:
        return None
    return {
        "name": "show_document_set",
        "arguments": {
            "title": f"Resultat {case.case_id}",
            "source_ids": result["presentation_source_ids"],
        },
    }


def deterministic_find_result(case: GoldCase) -> dict:
    """Materialize the shared mocked tool result before presentation."""
    return {
        "status": "completed",
        "query": case.search_query,
        "mode": case.mode,
        "source_ids": list(case.expected_source_ids),
        "presentation_source_ids": list(case.expected_source_ids),
    }


def _group_session(floor: str | None = None) -> GroupVoiceSession:
    session = GroupVoiceSession(
        panel_id="panel",
        member_ids={EXPERT_ID, "expert-b"},
        member_names={EXPERT_ID: "A", "expert-b": "B"},
    )
    if floor is not None:
        session.grant_floor(floor)
    return session


async def capture_case(case: GoldCase, channel: Channel) -> Capture:
    events: list[dict] = []
    call = presentation_call(case)
    calls = [] if call is None else [call]

    async def emit(payload: dict) -> None:
        events.append(deepcopy(payload))

    if channel == "text":
        await _send_workspace_tools(
            emit,
            {"thread_id": EXPERT_ID, "request_id": TURN_ID},
            calls,
        )
    elif channel == "voice":
        runtime = object.__new__(LiveSpeechRuntime)
        runtime._emit_json = emit
        runtime._turn_id = TURN_ID
        runtime._turn_cancel = asyncio.Event()
        await runtime._client_tools(TURN_ID)(calls)
    else:
        runtime = object.__new__(GroupVoiceAudioRuntime)
        runtime._emit_json = emit
        runtime.session = _group_session(EXPERT_ID)
        await runtime.emit_workspace_tool(
            calls, expert_id=EXPERT_ID, turn_id=TURN_ID,
        )
    state = _state_snapshot(case)
    return Capture(
        channel=channel,
        case_id=case.case_id,
        expected_gallery=case.expected_gallery,
        expected_source_ids=case.expected_source_ids,
        mode=case.mode,
        state_before=state,
        raw_events=tuple(events),
        input_call_after=deepcopy(call),
    )


async def capture_group_without_floor() -> tuple[dict, ...]:
    """Exercise the group adapter after the originating expert loses the floor."""
    events: list[dict] = []

    async def emit(payload: dict) -> None:
        events.append(deepcopy(payload))

    runtime = object.__new__(GroupVoiceAudioRuntime)
    runtime._emit_json = emit
    runtime.session = _group_session("expert-b")
    await runtime.emit_workspace_tool(
        [
            {
                "name": "show_document_set",
                "arguments": {"title": "Late", "source_ids": ["src-late"]},
            }
        ],
        expert_id=EXPERT_ID,
        turn_id=TURN_ID,
    )
    return tuple(events)


async def capture_interrupted(channel: Literal["voice", "group"]) -> tuple[dict, ...]:
    """Invoke an already-issued adapter callback after its turn is stale."""
    events: list[dict] = []

    async def emit(payload: dict) -> None:
        events.append(deepcopy(payload))

    call = [{
        "name": "show_document_set",
        "arguments": {"title": "Late", "source_ids": ["src-late"]},
    }]
    if channel == "voice":
        runtime = object.__new__(LiveSpeechRuntime)
        runtime._emit_json = emit
        runtime._turn_id = TURN_ID
        runtime._turn_cancel = asyncio.Event()
        callback = runtime._client_tools(TURN_ID)
        runtime._turn_cancel.set()
        await callback(call)
    else:
        runtime = object.__new__(GroupVoiceAudioRuntime)
        runtime._emit_json = emit
        runtime.session = _group_session(EXPERT_ID)
        callback = partial(
            runtime.emit_workspace_tool, expert_id=EXPERT_ID, turn_id=TURN_ID,
        )
        runtime.session.grant_floor("expert-b")
        await callback(call)
    return tuple(events)


def _state_snapshot(case: GoldCase) -> dict:
    return {
        "active_source_ids": list(case.current_source_ids),
        "mode": case.mode,
    }
