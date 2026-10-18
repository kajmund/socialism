"""Isolated IntentDecision contracts against the frozen 50 gold cases."""

from __future__ import annotations

import pytest

from scripts.document_presentation_benchmark.cases import build_gold_cases, state_for_case
from app.services.expert_async_tools import (
    LibraryToolScope,
    PlannedCall,
    begin_library_tools,
    complete_tool_episode,
)
from app.services.expert_reasoning_turn import route_expert_turn
from app.services.library_workspace_turn import finish_workspace_turn
from app.services.prompt_catalog import default_prompts
from app.services.workspace_intent import (
    IntentDecision,
    apply_intent_to_find_arguments,
    decide_workspace_intent,
    filter_specs_for_intent,
    presentation_tools_allowed,
)

_PRESENTATION = {
    "show": "gallery",
    "count": "none",
    "analyze": "none",
    "ambiguous": "uncertain",
}


def test_intent_decision_matches_all_fifty_gold_cases() -> None:
    cases = build_gold_cases()
    assert len(cases) == 50
    mismatches: list[str] = []
    for case in cases:
        decision = decide_workspace_intent(case.message, state_for_case(case))
        expected_presentation = _PRESENTATION[case.intent]
        if decision.operation != case.mode:
            mismatches.append(
                f"{case.case_id}: operation {decision.operation!r} != {case.mode!r}"
            )
        if decision.presentation != expected_presentation:
            mismatches.append(
                f"{case.case_id}: presentation {decision.presentation!r} "
                f"!= {expected_presentation!r}"
            )
        if case.mode in {"filter", "within", "extend"} and case.current_source_ids:
            if decision.scope != "active_document_set":
                mismatches.append(f"{case.case_id}: scope should be active_document_set")
        elif decision.scope != "catalog" and case.mode == "replace":
            # replace without relying on the prior set
            if not case.current_source_ids:
                mismatches.append(f"{case.case_id}: scope should be catalog")
    assert mismatches == []


def test_uncertain_and_none_block_gallery_tools() -> None:
    none = IntentDecision("replace", "none", "catalog", "hyresavtal")
    uncertain = IntentDecision("replace", "uncertain", "catalog", "hyresavtal")
    gallery = IntentDecision("replace", "gallery", "catalog", "hyresavtal")
    assert presentation_tools_allowed(none) is False
    assert presentation_tools_allowed(uncertain) is False
    assert presentation_tools_allowed(gallery) is True
    specs = [
        {"function": {"name": "find_documents"}},
        {"function": {"name": "show_document_set"}},
        {"function": {"name": "show_document"}},
    ]
    kept = filter_specs_for_intent(specs, uncertain)
    assert [s["function"]["name"] for s in kept] == ["find_documents"]


def test_apply_intent_locks_find_mode_and_query() -> None:
    intent = IntentDecision("within", "gallery", "active_document_set", "hyresavtal")
    assert apply_intent_to_find_arguments(
        {"query": "employment agreement", "mode": "replace"},
        intent,
    ) == {"query": "hyresavtal", "mode": "within"}


def test_apply_intent_keeps_model_query_without_type_label() -> None:
    intent = IntentDecision("filter", "gallery", "active_document_set", "ner")
    model_query = "hyresavtal lokal bostad andrahandsuthyrning arrendeavtal lägenhetsarrende"
    assert apply_intent_to_find_arguments(
        {"query": model_query, "mode": "filter"},
        intent,
    ) == {"query": model_query, "mode": "filter"}


def test_context_dependent_follow_up_does_not_clobber_query() -> None:
    state = {
        "active_document_set_id": "current",
        "document_sets": [
            {"id": "current", "title": "Hyresavtal", "source_ids": ["src-1", "src-2"]}
        ],
    }
    intent = decide_workspace_intent("Filtrera ner dokumenten", state)
    assert intent.operation == "filter"
    assert intent.query == "ner"
    model_query = "hyresavtal arrendeavtal lägenhetsarrende"
    assert apply_intent_to_find_arguments(
        {"query": model_query, "mode": "filter"},
        intent,
    )["query"] == model_query


def test_apply_intent_overrides_query_when_message_names_type() -> None:
    state = {
        "active_document_set_id": "current",
        "document_sets": [
            {"id": "current", "title": "Hyresavtal", "source_ids": ["src-1"]}
        ],
    }
    intent = decide_workspace_intent(
        "Filtrera den aktuella dokumentmängden till hyresavtal.",
        state,
    )
    assert intent.query == "hyresavtal"
    assert apply_intent_to_find_arguments(
        {"query": "lease agreement", "mode": "replace"},
        intent,
    ) == {"query": "hyresavtal", "mode": "filter"}


def test_natural_swedish_follow_up_is_filter_gallery() -> None:
    state = {
        "active_document_set_id": "current",
        "document_sets": [
            {"id": "current", "title": "Hyresavtal", "source_ids": ["src-1", "src-2"]}
        ],
    }
    decision = decide_workspace_intent(
        "Visa bara dem med automatisk förlängning.",
        state,
    )
    assert decision.operation == "filter"
    assert decision.presentation == "gallery"
    assert decision.scope == "active_document_set"


def test_filter_and_within_are_distinct_operations() -> None:
    state = {
        "active_document_set_id": "current",
        "document_sets": [
            {"id": "current", "title": "Hyresavtal", "source_ids": ["src-1"]}
        ],
    }
    filtered = decide_workspace_intent(
        "Filtrera den aktuella dokumentmängden till automatisk förlängning.",
        state,
    )
    within = decide_workspace_intent(
        "Sök inom den aktuella dokumentmängden efter automatisk förlängning.",
        state,
    )
    assert filtered.operation == "filter"
    assert within.operation == "within"
    assert filtered.scope == within.scope == "active_document_set"
    assert apply_intent_to_find_arguments({"mode": "replace"}, filtered)["mode"] == "filter"
    assert apply_intent_to_find_arguments({"mode": "replace"}, within)["mode"] == "within"


@pytest.mark.asyncio
async def test_route_locks_intent_and_strips_gallery_tools(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.document_tool_retrieval_enabled", False)
    monkeypatch.setattr("app.config.settings.expert_reasoning_route_enabled", False)
    scope = begin_library_tools(
        persona_id="p1",
        mode="interview",
        actor_user_id="u1",
        history=[],
        user_message="Hur många hyresavtal har vi? Svara bara hur många.",
        enabled=True,
        workspace=("ws-1", {}),
    )
    specs = [
        {"type": "function", "function": {"name": "find_documents", "parameters": {}}},
        {"type": "function", "function": {"name": "show_document_set", "parameters": {}}},
        {"type": "function", "function": {"name": "show_document", "parameters": {}}},
    ]
    await route_expert_turn(scope, default_prompts("sv"), "expert", ([], specs))
    assert scope.workspace_intent is not None
    assert scope.workspace_intent.presentation == "none"
    assert [s["function"]["name"] for s in specs] == ["find_documents"]


@pytest.mark.asyncio
async def test_continuation_cannot_defer_gallery_when_presentation_is_none(
    monkeypatch,
) -> None:
    scope = begin_library_tools(
        persona_id="p1",
        mode="interview",
        actor_user_id="u1",
        history=[],
        user_message="Hur många hyresavtal har vi?",
        enabled=True,
        workspace=("ws-1", {}),
    )
    scope.workspace_intent = IntentDecision(
        "replace", "none", "catalog", "hyresavtal",
    )

    async def run_one(_call, _work):
        return '{"source_ids":["a","b"],"document_count":2}'

    async def compose(work, _blob, _results, **kwargs):
        publish = kwargs["publish"]
        await publish(
            [
                PlannedCall(
                    "show-1",
                    "show_document_set",
                    {"title": "Hyresavtal", "source_ids": ["a", "b"]},
                )
            ]
        )
        return "Ni har två hyresavtal.", None

    async def no_reroute(*_a, **_k):
        return [], False

    monkeypatch.setattr("app.services.expert_async_tools._run_one", run_one)
    monkeypatch.setattr(
        "app.services.expert_tool_followup.compose_tool_episode", compose
    )
    monkeypatch.setattr(
        "app.services.expert_reasoning_turn.reroute_workspace_episode",
        no_reroute,
    )
    await scope.enter()
    try:
        text = await complete_tool_episode(
            scope,
            (PlannedCall("find-1", "find_documents", {"query": "hyresavtal", "mode": "replace"}),),
        )
    finally:
        await scope.finish()
    assert text == "Ni har två hyresavtal."
    assert not any(
        call.name in {"show_document", "show_document_set"}
        for call in scope.client_calls
    )


@pytest.mark.asyncio
async def test_finish_workspace_turn_drops_gallery_for_uncertain(monkeypatch) -> None:
    scope = LibraryToolScope(
        enabled=True,
        persona_id="expert",
        mode="character",
        actor_user_id="user",
        history=[],
        user_message="Vilka hyresavtal har vi?",
    )
    scope.workspace_intent = IntentDecision(
        "replace", "uncertain", "catalog", "hyresavtal",
    )
    scope.client_calls.append(
        PlannedCall(
            "gallery",
            "show_document_set",
            {"title": "Hyresavtal", "source_ids": ["src-1"]},
        )
    )
    emitted: list[list[dict]] = []

    async def emit(calls):
        emitted.append(calls)

    class _Session:
        async def get(self, *_a, **_k):
            return None

        def in_transaction(self) -> bool:
            return False

        async def rollback(self) -> None:
            return None

    async def _no_open(*_a, **_k):
        return None

    async def _no_ids(*_a, **_k):
        return set()

    monkeypatch.setattr(
        "app.services.library_workspace_turn.source_for_open_request",
        _no_open,
    )
    monkeypatch.setattr(
        "app.services.library_workspace_turn.artifact_for_open_request",
        _no_open,
    )
    monkeypatch.setattr(
        "app.services.library_workspace_turn.ready_document_ids",
        _no_ids,
    )
    await finish_workspace_turn(
        _Session(),
        scope,
        emit,
        workspace_id=None,
        actor_user_id=None,
        message="Vilka hyresavtal har vi?",
        history=[],
    )
    assert emitted == []
    assert scope.client_calls == []
