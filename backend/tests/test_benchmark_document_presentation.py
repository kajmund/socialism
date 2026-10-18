"""Deterministic coverage for the isolated document-presentation benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import benchmark_document_presentation as benchmark

BASELINES = Path(__file__).parent / "integration/baselines"


def _reply(name: str, arguments: dict) -> SimpleNamespace:
    call = SimpleNamespace(
        id=f"call-{name}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )
    return SimpleNamespace(content=None, tool_calls=[call])


def _complete_result(source_ids: list[str]) -> dict:
    return {
        "status": "completed",
        "completeness": "complete",
        "title": "Hyresavtal",
        "source_ids": source_ids,
        "presentation_source_ids": source_ids[:40],
        "counters": {"embedding_calls": 0},
    }


def test_gold_set_has_exactly_50_varied_paired_cases():
    cases = benchmark.build_gold_cases()

    assert len(cases) == 50
    assert len({case.message for case in cases}) == 50
    assert {case.mode for case in cases} == {"replace", "filter", "within", "extend"}
    assert {case.intent for case in cases} == {
        "show",
        "count",
        "analyze",
        "ambiguous",
    }
    assert any(case.current_source_ids for case in cases)

    for index in range(0, len(cases), 2):
        shown, not_shown = cases[index : index + 2]
        assert (
            shown.search_query,
            shown.mode,
            shown.current_source_ids,
            shown.expected_source_ids,
        ) == (
            not_shown.search_query,
            not_shown.mode,
            not_shown.current_source_ids,
            not_shown.expected_source_ids,
        )
        assert shown.expected_gallery is True
        assert not_shown.expected_gallery is False


def test_frozen_live_result_is_not_approved_for_production():
    result = json.loads(
        (BASELINES / "document-presentation-deterministic-v1.json").read_text()
    )
    assert result["do_not_overwrite"] is True
    assert result["acceptance"]["approved_for_production"] is False
    assert result["acceptance"]["correct_presentation_decisions"] == 39
    assert result["acceptance"]["paired_arm_selections_equal"] == 50


@pytest.mark.asyncio
async def test_presentation_is_stripped_before_same_search_handler():
    calls: list[dict] = []

    async def production_handler(arguments, _state):
        calls.append(arguments)
        return {"source_ids": ["src-1", "src-2"]}

    state = SimpleNamespace()
    plain = {"query": "Hyresavtal", "mode": "replace"}
    gallery = {**plain, "presentation": "gallery"}

    plain_result = await production_handler(
        benchmark.production_find_arguments(plain),
        state,
    )
    gallery_result = await production_handler(
        benchmark.production_find_arguments(gallery),
        state,
    )

    assert calls == [plain, plain]
    assert gallery_result == plain_result


def test_validator_preserves_800_full_ids_and_uses_40_presentation_ids():
    full_ids = [f"src-{index}" for index in range(800)]
    original = list(full_ids)
    result = _complete_result(full_ids)

    decision = benchmark.validate_gallery_continuation(
        {"presentation": "gallery"},
        result,
        allowed_source_ids=frozenset(full_ids),
    )

    assert decision.accepted is True
    assert decision.call["arguments"]["source_ids"] == full_ids[:40]
    assert result["source_ids"] == original
    assert len(result["source_ids"]) == 800


@pytest.mark.parametrize(
    ("arguments", "change", "reason"),
    [
        ({}, {}, "presentation_not_gallery"),
        ({"presentation": "gallery"}, {"status": "failed"}, "find_not_completed"),
        (
            {"presentation": "gallery"},
            {"completeness": "partial"},
            "find_not_complete",
        ),
        (
            {"presentation": "gallery"},
            {"source_ids": ["src-1", "src-1"]},
            "invalid_full_source_ids",
        ),
        (
            {"presentation": "gallery"},
            {"presentation_source_ids": []},
            "invalid_presentation_source_ids",
        ),
        (
            {"presentation": "gallery"},
            {"presentation_source_ids": ["src-3"]},
            "presentation_not_subset",
        ),
    ],
)
def test_validator_fails_closed(arguments, change, reason):
    result = {**_complete_result(["src-1", "src-2"]), **change}
    decision = benchmark.validate_gallery_continuation(
        arguments,
        result,
        allowed_source_ids=frozenset({"src-1", "src-2", "src-3"}),
    )
    assert decision == benchmark.PresentationDecision(False, reason)


def test_validator_rejects_id_outside_fixture_inventory():
    decision = benchmark.validate_gallery_continuation(
        {"presentation": "gallery"},
        _complete_result(["src-1", "src-other"]),
        allowed_source_ids=frozenset({"src-1"}),
    )
    assert decision.reason == "source_outside_inventory"


@pytest.mark.asyncio
async def test_paired_valid_treatment_reuses_shared_find(monkeypatch):
    case = next(
        case
        for case in benchmark.build_gold_cases()
        if case.expected_gallery and case.mode == "replace"
    )
    source_ids = list(case.expected_source_ids)
    external_calls = {"jev": 0, "llm": 0, "find": 0}
    replies = [
        _reply(
            "find_documents",
            {
                "query": case.search_query,
                "mode": case.mode,
                "presentation": "gallery",
            },
        ),
        _reply(
            "show_document_set",
            {"title": "Hyresavtal", "source_ids": source_ids},
        ),
    ]

    async def fake_expose(**_kwargs):
        external_calls["jev"] += 1
        route = SimpleNamespace(
            ranking=("find_documents",),
            scores={"find_documents": 1.0},
            require_tool=True,
        )
        return [{"function": {"name": "find_documents"}}], route

    async def fake_complete(_messages, _tools, **_kwargs):
        external_calls["llm"] += 1
        return replies.pop(0)

    async def fake_find(_arguments, _state):
        external_calls["find"] += 1
        return _complete_result(source_ids)

    monkeypatch.setattr(benchmark, "expose_workspace_tools", fake_expose)
    monkeypatch.setattr(benchmark, "complete_with_tools", fake_complete)
    baseline, treatment = await benchmark._run_paired_case(
        case,
        environment=SimpleNamespace(inventory=frozenset(source_ids)),
        find_runner=fake_find,
    )

    assert treatment.continuation == "deterministic"
    assert treatment.presentation_decision_correct is True
    assert treatment.calls == benchmark.CallCounts(llm=1, jev=1, embedding=0)
    assert baseline.calls == benchmark.CallCounts(llm=2, jev=2, embedding=0)
    assert baseline.source_ids == treatment.source_ids == source_ids
    assert baseline.search_arguments == treatment.search_arguments == {
        "query": case.search_query,
        "mode": case.mode,
    }
    assert baseline.first_arguments == treatment.first_arguments
    assert external_calls == {"jev": 2, "llm": 2, "find": 1}
    assert benchmark.summarize_results([baseline, treatment])["comparison"][
        "paired_selection_equality"
    ] == {"equal": 1, "total": 1, "all_equal": True}


@pytest.mark.asyncio
async def test_absent_presentation_uses_current_baseline_continuation(monkeypatch):
    case = next(
        case
        for case in benchmark.build_gold_cases()
        if not case.expected_gallery and case.mode == "replace"
    )
    source_ids = list(case.expected_source_ids)
    replies = [
        _reply(
            "find_documents",
            {"query": case.search_query, "mode": case.mode},
        ),
        SimpleNamespace(content="Det finns fyra dokument.", tool_calls=[]),
        SimpleNamespace(content="Det finns fyra dokument.", tool_calls=[]),
    ]

    async def fake_expose(**_kwargs):
        route = SimpleNamespace(
            ranking=("find_documents",),
            scores={"find_documents": 1.0},
            require_tool=True,
        )
        return [{"function": {"name": "find_documents"}}], route

    async def fake_complete(_messages, _tools, **_kwargs):
        return replies.pop(0)

    async def fake_find(_arguments, _state):
        return _complete_result(source_ids)

    monkeypatch.setattr(benchmark, "expose_workspace_tools", fake_expose)
    monkeypatch.setattr(benchmark, "complete_with_tools", fake_complete)
    baseline, treatment = await benchmark._run_paired_case(
        case,
        environment=SimpleNamespace(inventory=frozenset(source_ids)),
        find_runner=fake_find,
    )

    assert treatment.continuation == "baseline"
    assert treatment.validation_reason == "presentation_not_gallery"
    assert treatment.presentation_decision_correct is True
    assert baseline.source_ids == treatment.source_ids == source_ids
    assert baseline.calls == treatment.calls == benchmark.CallCounts(
        llm=2,
        jev=2,
        embedding=0,
    )


@pytest.mark.asyncio
async def test_all_50_cases_call_find_once_and_share_selection(monkeypatch):
    cases = benchmark.build_gold_cases()
    current_case: benchmark.GoldCase | None = None
    find_calls = 0

    async def fake_expose(**_kwargs):
        route = SimpleNamespace(
            ranking=("find_documents",),
            scores={"find_documents": 1.0},
            require_tool=True,
        )
        return [{"function": {"name": "find_documents"}}], route

    async def fake_complete(messages, _tools, **_kwargs):
        if messages[-1]["role"] == "user":
            arguments = {
                "query": current_case.search_query,
                "mode": current_case.mode,
            }
            if current_case.expected_gallery:
                arguments["presentation"] = "gallery"
            return _reply("find_documents", arguments)
        return SimpleNamespace(content="Klart.", tool_calls=[])

    async def fake_find(arguments, state):
        nonlocal find_calls
        find_calls += 1
        assert arguments == {
            "query": current_case.search_query,
            "mode": current_case.mode,
        }
        assert state == benchmark._state_for_case(current_case)
        return _complete_result(list(current_case.expected_source_ids))

    monkeypatch.setattr(benchmark, "expose_workspace_tools", fake_expose)
    monkeypatch.setattr(benchmark, "complete_with_tools", fake_complete)
    inventory = frozenset(
        source_id
        for case in cases
        for source_id in case.expected_source_ids
    )
    for case in cases:
        current_case = case
        baseline, treatment = await benchmark._run_paired_case(
            case,
            environment=SimpleNamespace(inventory=inventory),
            find_runner=fake_find,
        )
        assert baseline.source_ids == treatment.source_ids
        assert baseline.first_arguments == treatment.first_arguments
        assert baseline.search_arguments == treatment.search_arguments

    assert find_calls == 50
