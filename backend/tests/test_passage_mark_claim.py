"""A claimed mark has to become a focus_anchor call on the same turn."""

from types import SimpleNamespace

import pytest

from app.services.expert_async_tools import (
    PlannedCall,
    ToolWork,
    begin_library_tools,
    complete_tool_episode,
)
from app.services.expert_reasoning_episode import ExpertEpisode, continue_expert_episode
from app.services.passage_mark_claim import mark_followup_needed

_FOCUS = {"type": "function", "function": {"name": "focus_anchor", "parameters": {}}}


def test_only_a_finished_mark_without_the_tool_needs_another_round():
    specs = (_FOCUS,)
    assert mark_followup_needed("Nu är de markerade — 8.1.", [], specs)
    assert mark_followup_needed("Nu ligger de tre markerade i vyn.", [], specs)
    assert mark_followup_needed("Jag har markerat passagen.", [], specs)
    assert not mark_followup_needed("Nu är de markerade.", ["focus_anchor"], specs)
    assert not mark_followup_needed("Det är inte markerat.", [], specs)
    assert not mark_followup_needed("Erik har markerat stycket.", [], specs)
    assert not mark_followup_needed("Vill du att jag markerar den?", [], specs)
    assert not mark_followup_needed("8.1 markerades aldrig.", [], specs)
    assert not mark_followup_needed("Nu är de markerade.", [], ())


@pytest.mark.asyncio
async def test_a_mark_claim_without_a_call_asks_for_each_passage(monkeypatch):
    seen: list[dict] = []
    published: list[str] = []

    async def complete(messages, _specs, **_kwargs):
        seen.append(messages[-1])
        if len(seen) == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[SimpleNamespace(
                    id="mark-8-1",
                    function=SimpleNamespace(
                        name="focus_anchor",
                        arguments='{"source_id":"doc","quote":"8.1"}',
                    ),
                )],
            )
        return SimpleNamespace(content="Klart.", tool_calls=None)

    async def publish(calls):
        published.extend(call.name for call in calls)

    async def run_call(call, _work):
        raise AssertionError(call.name)

    monkeypatch.setattr("app.services.expert_reasoning_episode.complete_with_tools", complete)
    work = ToolWork(
        persona_id="alfons",
        mode="character",
        actor_user_id="user",
        history=[],
        user_message="Markera 8.1",
        calls=(),
        episode=ExpertEpisode(
            messages=(
                {"role": "user", "content": "Markera 8.1"},
                {"role": "assistant", "content": "Nu är de markerade — 8.1."},
            ),
            specs=(_FOCUS,),
            prompt_key="chat.mode.in_character",
            reasoning_content=None,
        ),
    )
    text, _reasoning = await continue_expert_episode(work, [], run_call=run_call, publish=publish)
    assert seen[0]["role"] == "user"
    assert "marks_missing" in seen[0]["content"]
    assert published == ["focus_anchor"]
    assert text == "Klart."


@pytest.mark.asyncio
async def test_a_later_passage_mark_is_kept_for_the_turn(monkeypatch):
    async def compose(_work, _blob, _results, *, continue_episode, run_call, publish):
        await publish([PlannedCall("mark-1", "focus_anchor", {"source_id": "doc", "quote": "8.1"})])
        return "Klart.", None

    monkeypatch.setattr("app.services.expert_tool_followup.compose_tool_episode", compose)
    scope = begin_library_tools(
        persona_id="alfons",
        mode="character",
        actor_user_id="user",
        history=[],
        user_message="Markera 8.1",
        enabled=True,
    )
    await scope.enter()
    try:
        assert await complete_tool_episode(scope, ()) == "Klart."
    finally:
        await scope.finish()
    assert [(call.name, call.arguments["quote"]) for call in scope.client_calls] == [
        ("focus_anchor", "8.1"),
    ]
