"""Jev ranks existing workspace tools and leaves the choice to the model."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.document_navigation import match_section, unit_on_page, window_around
from app.services.document_tool_retrieval import (
    expose_workspace_tools,
    has_document_target,
    requires_tool_call,
    select_exposed,
    state_filtered_specs,
)
from app.services.expert_async_tools import _planned_calls
from app.services.leaked_tool_text import read_promise_arguments
from app.services.prompt_catalog import default_prompts


def _spec(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {}}}


class _Jev:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.questions: dict | None = None
        self.state: dict | None = None

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.questions = questions
        self.state = state
        return JevSystemOneResult(
            answers={key: {"noul": self.scores[key]} for key in questions},
            model=model,
            latency_ms=1,
            input_chars=1,
            usage=JevUsage(),
            raw={},
        )


class _Section:
    def __init__(self, title: str) -> None:
        self.title = title


def test_window_keeps_paragraphs_around_a_known_quote():
    text = "Ett.\n\nTvå.\n\nKunden får säga upp avtalet.\n\nFyra.\n\nFem."
    assert window_around(text, "säga upp", 1) == "Två.\n\nKunden får säga upp avtalet.\n\nFyra."


def test_section_match_is_exact_or_a_single_containing_title():
    rows = [_Section("12 Övrigt"), _Section("12.4 Förtida uppsägning")]
    assert match_section(rows, "12.4") is rows[1]
    assert match_section(rows, "12") is None


def test_document_tools_require_a_document_target():
    specs = [_spec("search_knowledge"), _spec("read_source"), _spec("focus_anchor")]
    assert has_document_target({"document_mentions": [{"source_object_id": "abc"}]}) is True
    assert has_document_target({"documents": [], "selection": None}) is False
    kept = [spec["function"]["name"] for spec in state_filtered_specs(specs, {"documents": []})]
    assert kept == ["search_knowledge"]


def test_exposure_keeps_a_complement_below_the_gap(monkeypatch):
    scores = {
        "search_knowledge": 0.96,
        "focus_anchor": 0.88,
        "show_document": 0.81,
        "read_source": 0.30,
        "export_document": 0.07,
    }
    monkeypatch.setattr(settings, "document_tool_relevance_floor", 0.2)
    monkeypatch.setattr(settings, "document_tool_relevance_top_k", 8)
    monkeypatch.setattr(settings, "document_tool_relevance_gap", 0.40)
    monkeypatch.setattr(settings, "document_tool_relevance_complement_floor", 0.25)
    assert select_exposed(scores) == [
        "search_knowledge",
        "focus_anchor",
        "show_document",
        "read_source",
    ]


@pytest.mark.asyncio
async def test_scores_are_advisory_and_ordered(monkeypatch):
    monkeypatch.setattr(settings, "document_tool_relevance_floor", 0.2)
    monkeypatch.setattr(settings, "document_tool_relevance_top_k", 8)
    monkeypatch.setattr(settings, "document_tool_relevance_gap", 0.55)
    monkeypatch.setattr(settings, "document_tool_relevance_complement_floor", 0.45)
    prompts = default_prompts("sv")
    specs = [_spec("show_document"), _spec("search_knowledge"), _spec("export_document")]
    jev = _Jev({"show_document": 0.50, "search_knowledge": 0.97, "export_document": 0.05})
    exposed, record = await expose_workspace_tools(
        prompts=prompts,
        specs=specs,
        message="Var står det om vite?",
        workspace_state={"documents": [{"source_id": "doc", "page": 1}]},
        jev=jev,
    )
    assert [spec["function"]["name"] for spec in exposed] == ["search_knowledge", "show_document"]
    assert exposed[0]["function"]["description"].startswith("jev_relevance: 0.97")
    assert "måste du anropa minst ett verktyg" in exposed[0]["function"]["description"]
    assert record.fallback is False
    assert record.require_tool is True
    assert record.ranking[0] == "search_knowledge"


@pytest.mark.asyncio
async def test_document_scores_use_the_current_request_not_available_files(monkeypatch):
    monkeypatch.setattr(settings, "document_tool_relevance_floor", 0.2)
    monkeypatch.setattr(settings, "document_tool_relevance_top_k", 8)
    monkeypatch.setattr(settings, "document_tool_relevance_gap", 0.55)
    monkeypatch.setattr(settings, "document_tool_relevance_complement_floor", 0.45)
    specs = [_spec("show_document"), _spec("read_source"), _spec("search_knowledge")]
    jev = _Jev({name: 0.9 for name in ("show_document", "read_source", "search_knowledge")})
    _exposed, record = await expose_workspace_tools(
        prompts=default_prompts("sv"),
        specs=specs,
        message="Bra, tack",
        workspace_state={"documents": [{"source_id": "contract", "filename": "Avtal.pdf"}]},
        jev=jev,
    )
    assert record.require_tool is True
    assert jev.state is not None
    assert "workspace_state" not in jev.state
    assert "Avtal.pdf" not in str(jev.state), (jev.state, jev.questions)


@pytest.mark.asyncio
async def test_jev_failure_keeps_state_filtered_catalog():
    class Broken:
        async def ask(self, *, state, questions, model, timeout_seconds):
            raise JevClientError("timed out", category="timeout")

    specs = [_spec("search_knowledge"), _spec("read_source")]
    exposed, record = await expose_workspace_tools(
        prompts=default_prompts("sv"),
        specs=specs,
        message="Gå till sida 3",
        workspace_state={"documents": []},
        jev=Broken(),
    )
    assert exposed == [specs[0]]
    assert record.fallback is True
    assert record.require_tool is False
    assert record.error_category == "timeout"


def test_lookup_tools_stay_exposed_below_the_floor(monkeypatch):
    monkeypatch.setattr(settings, "document_tool_relevance_floor", 0.2)
    monkeypatch.setattr(settings, "document_tool_relevance_top_k", 8)
    monkeypatch.setattr(settings, "document_tool_relevance_gap", 0.55)
    scores = {
        "get_relations": 0.70,
        "search_knowledge": 0.12,
        "export_document": 0.05,
    }
    assert select_exposed(scores, pinned=frozenset({"search_knowledge"})) == [
        "get_relations",
        "search_knowledge",
    ]


def test_high_relevance_requires_a_tool_call(monkeypatch):
    monkeypatch.setattr(settings, "document_tool_require_score", 0.40)
    assert requires_tool_call(("get_relations",), {"get_relations": 0.65}) is True
    assert requires_tool_call(("search_knowledge",), {"search_knowledge": 0.12}) is False
    assert requires_tool_call((), {}) is False


def test_unit_on_page_uses_the_page_span():
    assert unit_on_page(page_start=3, page_end=4, locator=None, page=3)
    assert unit_on_page(page_start=3, page_end=4, locator=None, page=4)
    assert not unit_on_page(page_start=3, page_end=4, locator=None, page=2)
    assert unit_on_page(page_start=None, page_end=None, locator="page:3", page=3)


def test_read_promise_becomes_read_source_for_that_page():
    text = "Jag läser igenom sidan 3 i avtalet och återkommer."
    state = {"documents": [{"source_id": "src-1", "page": 3}]}
    assert read_promise_arguments(text, state) == {"source_id": "src-1", "page": 3}
    assert read_promise_arguments("Sidan 3 handlar om priset.", state) is None
    calls = _planned_calls(
        SimpleNamespace(tool_calls=None, content=text),
        text,
        [{"role": "user", "content": "vad innehåller den här sidan?"}],
        offered=frozenset({"read_source"}),
        consult=False,
        workspace_state=state,
    )
    assert [(call.name, call.arguments) for call in calls] == [
        ("read_source", {"source_id": "src-1", "page": 3})
    ]


def test_leaked_markup_cannot_call_unoffered_tool():
    text = '[[underlag]] {"tool":"start_research","arguments":{"question":"x"}}'
    calls = _planned_calls(
        SimpleNamespace(tool_calls=None, content=text),
        text,
        [{"role": "user", "content": "läs avtalet"}],
        offered=frozenset({"read_source"}),
        consult=False,
    )
    assert calls == []
