"""Workspace tool results trigger a Jev re-rank of the full catalog."""

from types import SimpleNamespace

import pytest

from app.services import expert_reasoning_turn
from app.services import expert_reasoning_episode
from app.services.expert_async_tools import ToolWork, begin_library_tools
from app.services.expert_reasoning_episode import ExpertEpisode, continue_expert_episode
from app.services.prompt_catalog import default_prompts


@pytest.mark.asyncio
async def test_reroute_uses_full_catalog_and_tool_result(monkeypatch):
    catalog = [
        {
            "type": "function",
            "function": {
                "name": "show_document_set",
                "description": "gallery",
                "parameters": {},
            },
        }
    ]
    scope = begin_library_tools(
        persona_id="expert-1",
        mode="character",
        actor_user_id="user-1",
        history=[],
        user_message="Visa alla hyresavtal",
        enabled=True,
        workspace=("workspace-1", {"documents": []}),
    )
    scope.workspace_prompts = default_prompts("sv")
    scope.workspace_tool_catalog = catalog
    captured = {}

    async def fake_expose(**kwargs):
        captured.update(kwargs)
        return catalog, SimpleNamespace(require_tool=False)

    monkeypatch.setattr(expert_reasoning_turn, "expose_workspace_tools", fake_expose)
    result, require_tool = await expert_reasoning_turn.reroute_workspace_episode(
        scope,
        '{"document_count": 2}',
    )

    assert result == catalog
    assert require_tool is False
    assert captured["specs"] == catalog
    assert captured["tool_result"] == '{"document_count": 2}'
    assert captured["reroute"] is True


@pytest.mark.asyncio
async def test_required_reroute_forces_the_continuation_tool_choice(monkeypatch):
    choices = []

    async def complete(_messages, _specs=None, *, tool_choice="auto", **_kwargs):
        choices.append(tool_choice)
        return SimpleNamespace(content="klart", tool_calls=None)

    async def unused(*_args, **_kwargs):
        raise AssertionError("no tool call expected")

    monkeypatch.setattr(expert_reasoning_episode, "complete_with_tools", complete)
    work = ToolWork(
        persona_id="expert-1",
        mode="character",
        actor_user_id="user-1",
        history=[],
        user_message="Visa alla hyresavtal",
        calls=(),
        episode=ExpertEpisode(
            messages=({"role": "user", "content": "Visa alla hyresavtal"},),
            specs=(),
            prompt_key="chat.mode.in_character",
            reasoning_content=None,
            tool_choice="required",
        ),
    )
    text, _reasoning = await continue_expert_episode(
        work,
        (),
        run_call=unused,
        publish=unused,
    )

    assert text == "klart"
    assert choices == ["required"]
