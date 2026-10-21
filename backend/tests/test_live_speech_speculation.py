import asyncio

import pytest

from app.services import live_speech_speculation as ls
from app.services.speculative_results import (
    normalize_query,
    speculative_result_for,
    speculative_results,
)


def test_normalize_query_folds_and_collapses():
    assert normalize_query("  Vilka AVTAL? ") == "vilka avtal"
    assert normalize_query(None) == ""


def test_speculative_result_for_looks_up_query_and_tool():
    mapping = {("find_documents", "vilka avtal"): '{"status":"completed"}'}
    with speculative_results(mapping):
        assert (
            speculative_result_for("find_documents", {"query": "Vilka avtal?"})
            == '{"status":"completed"}'
        )
        assert speculative_result_for("find_documents", {"query": "annat"}) is None
        assert speculative_result_for("create_document", {"query": "vilka avtal?"}) is None


def test_speculative_result_for_does_not_reuse_an_extended_query():
    mapping = {("find_documents", "vilka avtal"): '{"status":"completed"}'}
    with speculative_results(mapping):
        assert (
            speculative_result_for(
                "find_documents",
                {"query": "Vilka avtal löper ut nästa kvartal?"},
            )
            is None
        )


async def test_reader_prefetches_only_read_only_tools(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    async def fake_tool(call, _work):
        calls.append((call.name, call.arguments["query"]))
        return '{"status":"completed"}'

    monkeypatch.setattr(ls, "run_workspace_tool_call", fake_tool)
    reader = ls.SpeculativeReader(
        workspace_id="ws", user_id="u", workspace_state={}, min_chars=4, enabled=True,
    )
    reader.on_partial("Vilka avtal löper ut?")
    await asyncio.sleep(0.01)

    assert {name for name, _ in calls} == {"find_documents", "search_knowledge"}
    result = reader.matches("Vilka avtal löper ut?")
    assert result is not None
    assert result[("find_documents", "vilka avtal löper ut")] == '{"status":"completed"}'
    await reader.aclose()


async def test_reader_drops_mismatched_final(monkeypatch: pytest.MonkeyPatch):
    async def fake_tool(_call, _work):
        return '{"status":"completed"}'

    monkeypatch.setattr(ls, "run_workspace_tool_call", fake_tool)
    reader = ls.SpeculativeReader(
        workspace_id="ws", user_id="u", workspace_state={}, min_chars=4, enabled=True,
    )
    reader.on_partial("Vilka avtal löper ut?")
    await asyncio.sleep(0.01)
    assert reader.matches("Något helt annat") is None
    await reader.aclose()


async def test_reader_refuses_an_extended_final(monkeypatch: pytest.MonkeyPatch):
    async def fake_tool(_call, _work):
        return '{"status":"completed"}'

    monkeypatch.setattr(ls, "run_workspace_tool_call", fake_tool)
    reader = ls.SpeculativeReader(
        workspace_id="ws", user_id="u", workspace_state={}, min_chars=4, enabled=True,
    )
    reader.on_partial("Vilka avtal")
    await asyncio.sleep(0.01)
    assert reader.matches("Vilka avtal löper ut nästa kvartal?") is None
    assert reader.stats["rejected_mismatch"] == 1
    await reader.aclose()


async def test_reader_rejects_stale_workspace_permissions(monkeypatch: pytest.MonkeyPatch):
    async def fake_tool(_call, _work):
        return '{"status":"completed"}'

    monkeypatch.setattr(ls, "run_workspace_tool_call", fake_tool)
    reader = ls.SpeculativeReader(
        workspace_id="ws",
        user_id="u",
        workspace_state={"readable": True},
        min_chars=4,
        enabled=True,
    )
    reader.on_partial("Vilka avtal löper ut?")
    await asyncio.sleep(0.01)
    assert reader.matches("Vilka avtal löper ut?", {"readable": False}) is None
    assert reader.stats["rejected_mismatch"] == 1
    await reader.aclose()


async def test_reader_refuses_a_shorter_final(monkeypatch: pytest.MonkeyPatch):
    async def fake_tool(_call, _work):
        return '{"status":"completed"}'

    monkeypatch.setattr(ls, "run_workspace_tool_call", fake_tool)
    reader = ls.SpeculativeReader(
        workspace_id="ws", user_id="u", workspace_state={}, min_chars=4, enabled=True,
    )
    reader.on_partial("Vilka avtal löper ut nästa kvartal")
    await asyncio.sleep(0.01)
    assert reader.matches("Vilka avtal") is None
    assert reader.stats["incorrect"] == 1
    await reader.aclose()


async def test_reader_prefetches_read_only_tools_in_parallel(monkeypatch: pytest.MonkeyPatch):
    current = 0
    peak = 0

    async def fake_tool(_call, _work):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        return '{"status":"completed"}'

    monkeypatch.setattr(ls, "run_workspace_tool_call", fake_tool)
    reader = ls.SpeculativeReader(
        workspace_id="ws", user_id="u", workspace_state={}, min_chars=4, enabled=True,
    )
    reader.on_partial("Vilka avtal löper ut?")
    await asyncio.sleep(0.2)
    assert peak == 2
    await reader.aclose()


async def test_reader_disabled_does_nothing():
    reader = ls.SpeculativeReader(
        workspace_id="ws", user_id="u", workspace_state={}, min_chars=4, enabled=False,
    )
    reader.on_partial("Vilka avtal löper ut?")
    assert reader.matches("Vilka avtal löper ut?") is None
    await reader.aclose()
