"""CI-safe contracts for the nine-turn channel diagnostic and P0/P1 fixes."""

from __future__ import annotations

from types import SimpleNamespace

from app.schemas.workspace import WorkspaceState
from app.services.document_find.tool import normalize_find_mode
from app.services.expert_async_tools import (
    _planned_calls,
    begin_library_tools,
)
from app.services.persona_chat_turn_support import commit_library_message
from scripts.document_presentation_benchmark.diagnostic_runner import (
    _breakpoint,
    _case,
)


def test_diagnostic_scenarios_preserve_structured_modes() -> None:
    state = WorkspaceState()
    replace = _case(1, state)
    assert replace.message == "Visa alla hyresavtal."
    assert replace.mode == "replace"

    state = WorkspaceState.model_validate(
        {
            "view": "document_set",
            "document_sets": [
                {
                    "id": "active",
                    "title": "Urval",
                    "source_ids": ["src-lease_agreement-0"],
                }
            ],
            "active_document_set_id": "active",
        }
    )
    filtered = _case(2, state)
    extended = _case(3, state)

    assert filtered.mode == "filter"
    assert filtered.current_source_ids == ("src-lease_agreement-0",)
    assert extended.mode == "extend"
    assert extended.expected_source_ids[0] == "src-lease_agreement-0"


def test_breakpoint_identifies_first_failed_stage() -> None:
    row = {
        "trace": [
            {
                "stage": "initial_route",
                "exposed": ["find_documents"],
            },
            {
                "stage": "initial_model",
                "tool_calls": [{"name": "find_documents"}],
            },
            {
                "stage": "post_result_route",
                "exposed": ["show_document_set"],
            },
            {
                "stage": "continuation_model",
                "tool_calls": [],
            },
        ],
        "find_calls": [{"query": "hyresavtal"}],
        "find_results": [{"source_ids": ["src-lease_agreement-0"]}],
        "presentation_calls": [],
    }

    assert _breakpoint(row) == "continuation_model_decision"

    row["trace"][-1]["tool_calls"] = [{"name": "show_document_set"}]
    assert _breakpoint(row) == "client_delivery"

    row["presentation_calls"] = [{"name": "show_document_set"}]
    assert _breakpoint(row) == "completed"


def test_continuation_client_call_is_delivered_exactly_once() -> None:
    scope = begin_library_tools(
        persona_id="expert",
        mode="expert",
        actor_user_id="user",
        history=[],
        user_message="Visa alla hyresavtal.",
        enabled=True,
    )
    reply = SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="continuation-call",
                function=SimpleNamespace(
                    name="show_document_set",
                    arguments='{"title":"Hyresavtal","source_ids":["src-1"]}',
                ),
            )
        ],
    )

    planned = _planned_calls(
        reply,
        "",
        [],
        offered=frozenset({"show_document_set"}),
        consult=False,
        seen_call_ids=scope._planned_call_ids,
    )
    scope.defer(planned)
    scope.defer(planned)

    assert [call.id for call in planned] == ["continuation-call"]
    assert [call.id for call in scope.client_calls] == ["continuation-call"]
    assert "continuation-call" in scope._planned_call_ids


async def test_panel_guard_write_is_committed_before_return() -> None:
    committed = False

    class Session:
        def in_transaction(self) -> bool:
            return True

        async def commit(self) -> None:
            nonlocal committed
            committed = True

    async def guard(_session) -> bool:
        return True

    await commit_library_message(
        Session(),
        None,
        sme_expert_turn_request_id="group-turn",
        persist_guard=guard,
    )

    assert committed is True


def test_content_follow_up_with_active_set_coerces_replace_to_filter() -> None:
    assert (
        normalize_find_mode(
            "replace",
            has_current_set=True,
            query="Visa bara dem med automatisk förlängning.",
        )
        == "filter"
    )
    assert (
        normalize_find_mode(
            "replace",
            has_current_set=True,
            query="Visa alla hyresavtal.",
        )
        == "replace"
    )
    assert (
        normalize_find_mode(
            "extend",
            has_current_set=True,
            query="Lägg till anställningsavtalen.",
        )
        == "extend"
    )
    assert (
        normalize_find_mode(
            "replace",
            has_current_set=False,
            query="automatisk förlängning",
        )
        == "replace"
    )
