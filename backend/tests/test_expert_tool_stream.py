from types import SimpleNamespace

import pytest

from app.services import expert_episode_stream as ees
from app.services.expert_async_tools import ToolWork
from app.services.expert_reasoning_episode import ExpertEpisode, _RoundOutcome


def _work() -> ToolWork:
    work = ToolWork(
        persona_id="expert",
        mode="character",
        actor_user_id=None,
        history=[],
        user_message="Hur stor är omsättningen?",
        calls=(),
    )
    work.episode = ExpertEpisode(
        messages=({"role": "user", "content": "Hur stor är omsättningen?"},),
        specs=(),
        prompt_key="chat.mode.in_character",
        reasoning_content=None,
    )
    return work


async def test_stream_expert_episode_streams_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(
        _messages, _tools, *, prompt_key=None, tool_choice="auto", message_out=None,
    ):
        message_out.append(
            SimpleNamespace(
                content="Omsättningen är tolv.", tool_calls=None, reasoning_content=None,
            )
        )
        yield "Omsättningen "
        yield "är tolv."

    async def return_round(*_args, **_kwargs):
        return _RoundOutcome.RETURN, "Omsättningen är tolv."

    monkeypatch.setattr(ees, "stream_with_tools", fake_stream)
    monkeypatch.setattr(ees, "_trace_rows", lambda *_a, **_k: None)
    monkeypatch.setattr(ees, "_append_results", lambda *_a, **_k: [])
    monkeypatch.setattr(ees, "_result_by_id", lambda *_a, **_k: {})
    monkeypatch.setattr(ees, "_remember_transcript", lambda *_a, **_k: None)
    monkeypatch.setattr(ees, "_apply_opening_notice", lambda *_a, **_k: None)
    monkeypatch.setattr(ees, "_handle_call_free_round", return_round)

    async def run_call(*_args, **_kwargs):
        return ""

    async def publish(*_args, **_kwargs):
        return None

    reasoning_out: list[str | None] = []
    deltas = [
        delta
        async for delta in ees.stream_expert_episode(
            _work(), (), run_call=run_call, publish=publish, reasoning_out=reasoning_out,
        )
    ]
    assert deltas == ["Omsättningen ", "är tolv."]
    assert reasoning_out == [None]


async def test_apply_amendments_folds_amendment_into_transcript():
    import asyncio

    from app.services.turn_amendment import amendment_channel

    work = _work()
    messages = [{"role": "user", "content": "Vilka avtal löper ut?"}]
    queue = asyncio.Queue()
    await queue.put("fast avtalet är tre år")
    with amendment_channel(queue):
        assert await ees._apply_amendments(work, messages) is True
    assert {"role": "user", "content": "fast avtalet är tre år"} in messages
    assert work.episode is not None
    assert any("fast avtalet är tre år" == message["content"] for message in work.episode.messages)
