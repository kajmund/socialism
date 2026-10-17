"""Run Step A against all 50 gold cases and three real adapter seams."""

from __future__ import annotations

from copy import deepcopy

from scripts.channel_parity_experiment.adapters import (
    capture_case,
    capture_group_without_floor,
    capture_interrupted,
    presentation_call,
)
from scripts.channel_parity_experiment.normalize import normalize
from scripts.channel_parity_experiment.types import Channel
from scripts.document_presentation_benchmark.cases import build_gold_cases

CHANNELS: tuple[Channel, ...] = ("text", "voice", "group")


async def run_experiment() -> dict:
    cases = build_gold_cases()
    captures = [
        await capture_case(case, channel)
        for case in cases
        for channel in CHANNELS
    ]
    expected_calls = {case.case_id: presentation_call(case) for case in cases}
    rows = [
        _assess(capture, expected_calls[capture.case_id])
        for capture in captures
    ]
    floor_events = await capture_group_without_floor()
    interrupted_voice = await capture_interrupted("voice")
    interrupted_group = await capture_interrupted("group")
    summary = _summary(rows, floor_events, interrupted_voice, interrupted_group)
    return {
        "experiment": "channel-parity-step-a-v1",
        "case_source": "scripts.document_presentation_benchmark.cases.build_gold_cases",
        "adapter_seams": [
            "app.api.sme_ws._send_workspace_tools",
            "app.services.live_speech_runtime.LiveSpeechRuntime._client_tools",
            "app.services.sme_group_voice_runtime.GroupVoiceAudioRuntime.emit_workspace_tool",
        ],
        "summary": summary,
        "findings": [
            {
                "id": "group_missing_turn_id",
                "observed": summary["missing_turn_ids"] > 0,
                "count": summary["missing_turn_ids"],
            },
            {
                "id": "group_not_floor_gated",
                "observed": summary["non_floor_presentations"] > 0,
                "count": summary["non_floor_presentations"],
            },
            {
                "id": "voice_late_after_cancel",
                "observed": summary["late_after_cancel"]["voice"] > 0,
                "count": summary["late_after_cancel"]["voice"],
            },
            {
                "id": "group_late_after_cancel",
                "observed": summary["late_after_cancel"]["group"] > 0,
                "count": summary["late_after_cancel"]["group"],
            },
        ],
        "approved_for_step_b": False,
    }


def _assess(capture, expected_call: dict | None) -> dict:
    semantic = normalize(capture)
    expected_sequence = () if expected_call is None else ("show_document_set",)
    expected_ids = () if expected_call is None else capture.expected_source_ids
    input_preserved = capture.input_call_after == deepcopy(expected_call)
    state_preserved = capture.state_before["mode"] == capture.mode
    semantic_match = (
        semantic.sequence == expected_sequence
        and semantic.source_ids == expected_ids
        and input_preserved
        and state_preserved
    )
    return {
        "channel": capture.channel,
        "case_id": capture.case_id,
        "semantic_match": semantic_match,
        "gallery_presented": bool(semantic.sequence),
        "expected_gallery": capture.expected_gallery,
        "selection_correct": semantic.source_ids == expected_ids,
        "mode_state_preserved": input_preserved and state_preserved,
        "duplicates": semantic.duplicate_count,
        "missing_turn_id": bool(semantic.sequence) and not semantic.turn_id_present,
    }


def _summary(
    rows: list[dict],
    floor_events: tuple[dict, ...],
    interrupted_voice: tuple[dict, ...],
    interrupted_group: tuple[dict, ...],
) -> dict:
    total = len(rows)
    return {
        "gold_cases": total // len(CHANNELS),
        "channel_executions": total,
        "semantic_parity": sum(row["semantic_match"] for row in rows),
        "semantic_parity_target": total,
        "incorrect_auto_displays": sum(
            row["gallery_presented"] and not row["expected_gallery"] for row in rows
        ),
        "wrong_selections_or_modes": sum(
            not row["selection_correct"] or not row["mode_state_preserved"] for row in rows
        ),
        "duplicates": sum(row["duplicates"] for row in rows),
        "missing_turn_ids": sum(row["missing_turn_id"] for row in rows),
        "non_floor_presentations": _presentation_count(floor_events),
        "late_after_cancel": {
            "voice": _presentation_count(interrupted_voice),
            "group": _presentation_count(interrupted_group),
        },
    }


def _presentation_count(events: tuple[dict, ...]) -> int:
    return sum(
        event.get("name") == "show_document_set"
        and event.get("type") in {"workspace_tool", "workspace.tool"}
        for event in events
    )
