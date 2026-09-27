from __future__ import annotations

import pytest

from app.services.expert_chat_evidence_tool import (
    evidence_lookup_question,
    evidence_tool_handler_for_chat,
)


@pytest.mark.parametrize(
    "text",
    ["hej", "Hej!", "hejsan", "god morgon", "tack", "ok", "hello", ""],
)
def test_greetings_are_not_evidence_questions(text: str):
    assert evidence_lookup_question(text) is None


def test_an_asked_question_is_kept():
    assert evidence_lookup_question("  Vad säger avtalslagen om hävning? ") == (
        "Vad säger avtalslagen om hävning?"
    )


async def test_greeting_does_not_open_a_session():
    def factory():
        raise AssertionError("evidence lookup opened a session")

    handler = evidence_tool_handler_for_chat(
        customer_id=1,
        prompts={},
        session_factory=factory,  # type: ignore[arg-type]
    )
    text = await handler({"question": "hej"})
    assert "Inget evidensuppslag" in text


async def test_question_reads_frozen_evidence_without_claims(monkeypatch):
    opened: list[object] = []

    class _Session:
        async def __aenter__(self):
            opened.append(self)
            return self

        async def __aexit__(self, *_args):
            return None

    async def fake_context(session, *, customer_id, question, prompts, include_claims):
        del prompts
        assert session is opened[0]
        assert customer_id == 7
        assert question == "Vad säger avtalslagen?"
        assert include_claims is False
        return "FRYST"

    monkeypatch.setattr(
        "app.services.expert_chat_evidence.reusable_expert_chat_evidence_context",
        fake_context,
    )
    handler = evidence_tool_handler_for_chat(
        customer_id=7,
        prompts={"chat.expert.research_evidence": "{evidence}"},
        session_factory=lambda: _Session(),  # type: ignore[arg-type]
    )
    assert await handler({"question": "Vad säger avtalslagen?"}) == "FRYST"
