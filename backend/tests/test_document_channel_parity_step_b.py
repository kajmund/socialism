"""CI-safe contracts for the observational Step B live harness."""

from __future__ import annotations

from collections import Counter, defaultdict
from types import SimpleNamespace

from app.serializers import profile_from_dict
from scripts.document_presentation_benchmark.cases import build_gold_cases
from scripts.document_presentation_benchmark.step_b_environment import EXPERT_PROFILE
from scripts.document_presentation_benchmark.step_b_runner import run_channel_matrix


def test_step_b_expert_profile_satisfies_runtime_schema() -> None:
    profile = profile_from_dict(EXPERT_PROFILE, "Benchmarkjuristen")
    assert profile.age == "45"


async def test_step_b_schedules_50_by_3_with_equal_initial_states(monkeypatch) -> None:
    admitted: list[tuple[str, str]] = []
    executions: list[dict] = []

    async def admit(spec, _factory):
        admitted.append((spec.case.case_id, spec.channel))
        return 1, "token"

    async def execute(_factory, **kwargs):
        executions.append(kwargs)
        await kwargs["on_client_tools"](
            [
                {
                    "name": "show_document_set",
                    "arguments": {"title": "Resultat", "source_ids": ["src"]},
                }
            ]
        )
        return SimpleNamespace(reply="Klart")

    monkeypatch.setattr(
        "scripts.document_presentation_benchmark.step_b_runner._admit",
        admit,
    )
    rows = await run_channel_matrix(
        build_gold_cases(),
        session_factory=object(),
        execute_turn=execute,
    )

    assert len(rows) == len(executions) == len(admitted) == 150
    assert Counter(row.channel for row in rows) == {
        "text": 50,
        "voice": 50,
        "group_voice": 50,
    }
    states = defaultdict(list)
    for kwargs in executions:
        states[kwargs["message"]].append(kwargs["workspace_state"].model_dump())
    assert all(len(case_states) == 3 for case_states in states.values())
    assert all(
        case_states[0] == case_states[1] == case_states[2]
        for case_states in states.values()
    )


async def test_step_b_uses_production_adapter_seams(monkeypatch) -> None:
    async def admit(_spec, _factory):
        return 1, "token"

    async def execute(_factory, **kwargs):
        await kwargs["on_client_tools"](
            [{"name": "show_document_set", "arguments": {"source_ids": ["src"]}}]
        )
        return SimpleNamespace(reply="Klart")

    monkeypatch.setattr(
        "scripts.document_presentation_benchmark.step_b_runner._admit",
        admit,
    )
    rows = await run_channel_matrix(
        build_gold_cases()[:1],
        session_factory=object(),
        execute_turn=execute,
    )

    assert [row.envelope["adapter"] for row in rows] == [
        "_send_workspace_tools",
        "LiveSpeechRuntime._client_tools",
        "GroupVoiceAudioRuntime.emit_workspace_tool",
    ]
    assert rows[0].presentation_calls[0]["type"] == "workspace_tool"
    assert rows[1].presentation_calls[0]["type"] == "workspace.tool"
    assert rows[2].presentation_calls[0]["type"] == "workspace.tool"
    assert rows[2].envelope["floor_owned_by_expert"] is True


async def test_step_b_records_failure_and_continues(monkeypatch) -> None:
    calls = 0

    async def admit(_spec, _factory):
        return 1, "token"

    async def stored_status(_factory, _request_id, *, default):
        return default

    async def execute(_factory, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("model unavailable")
        return SimpleNamespace(reply="Klart")

    monkeypatch.setattr(
        "scripts.document_presentation_benchmark.step_b_runner._admit",
        admit,
    )
    monkeypatch.setattr(
        "scripts.document_presentation_benchmark.step_b_runner._stored_status",
        stored_status,
    )
    rows = await run_channel_matrix(
        build_gold_cases()[:2],
        session_factory=object(),
        execute_turn=execute,
    )

    assert calls == 6
    assert sum(row.error is not None for row in rows) == 1
    failed = next(row for row in rows if row.error is not None)
    assert failed.error == {"type": "RuntimeError", "message": "model unavailable"}
    assert failed.lifecycle_status == "failed"

