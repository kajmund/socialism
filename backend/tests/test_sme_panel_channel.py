"""Panel replies follow the channel and only the experts who have a point."""

from __future__ import annotations

import pytest

from app.services.sme_panel_chat import channel_history, hand_aware_context, speakers_for_utterance


def test_channel_history_names_the_other_experts():
    history = channel_history(
        "a",
        {"a": "Sara", "b": "Daniel"},
        [("user", None, "Hej"), ("assistant", "b", "Jag håller med"), ("assistant", "a", "Inte jag")],
    )
    assert history == [
        ("user", "Hej"),
        ("user", "Daniel: Jag håller med"),
        ("assistant", "Inte jag"),
    ]


class _Expert:
    def __init__(self, expert_id: str, name: str) -> None:
        self.id = expert_id
        self.name = name


@pytest.mark.asyncio
async def test_only_experts_with_a_point_reply_in_the_channel(monkeypatch):
    async def only_daniel(self, _utterance, jev=None, raise_hand_prompt=None):
        self.raise_hand("b")
        return "b"

    monkeypatch.setattr(
        "app.services.sme_group_voice.GroupVoiceSession.decide_raise_hands",
        only_daniel,
    )
    chosen, hands, _session = await speakers_for_utterance(
        [_Expert("a", "Sara"), _Expert("b", "Daniel")],  # type: ignore[list-item]
        "Vad tror ni?",
        "Har {name} något att säga?",
    )
    assert [expert.name for expert in chosen] == ["Daniel"]
    assert hands == {"b"}


def test_a_raised_hand_is_part_of_the_reply_context():
    context = hand_aware_context("Du sitter i panelen.", ["Sara"])
    assert "något att tillägga om det som just sades" in context
    assert "Nämn inte handen" in context
    assert "Lämna det andra experter redan har sagt." in context
