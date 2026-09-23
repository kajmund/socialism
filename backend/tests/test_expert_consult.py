from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.database.models import Persona, PersonaMessage
from app.llm import set_tools_completer
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.services.dd.company_mcp import complete_text_with_company_tools
from app.services.expert_consult import (
    consult_handler_for_persona,
    expert_consult_handler_for_chat,
)
from app.services.expertgranskning.memory import (
    ExpertMemoryHit,
    set_expert_memory_factory,
)
from app.services.panel.competency import ExpertCompetency
from app.services.prompt_catalog import default_prompts


class RecordingMemory:
    def __init__(self) -> None:
        self.adds: list[dict[str, Any]] = []

    async def search(self, **_kwargs) -> list[ExpertMemoryHit]:
        return []

    async def add_chat_turn(self, **kwargs) -> list[ExpertMemoryHit]:
        self.adds.append(kwargs)
        return []


def _expert(expert_id: str, name: str, competence: str) -> Persona:
    return Persona(
        id=expert_id,
        customer_id=1,
        kind="expert",
        name=name,
        occ=competence,
        district="Stockholm",
        quote="",
        profile={
            "name": name,
            "kompetensomrade": competence,
            "yrkesbakgrund": competence,
        },
        tools=None,
    )


@pytest.mark.asyncio
async def test_tool_loop_dispatches_ask_expert():
    calls = 0
    handled: list[dict[str, Any]] = []

    async def complete(_messages, tools):
        nonlocal calls
        calls += 1
        assert [tool["function"]["name"] for tool in tools or []] == ["ask_expert"]
        if calls == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(
                        id="call-1",
                        function=SimpleNamespace(
                            name="ask_expert",
                            arguments='{"question":"När gäller regeln?"}',
                        ),
                    )
                ],
            )
        return SimpleNamespace(content="Roger har svarat.", tool_calls=None)

    async def handle(arguments):
        handled.append(arguments)
        return '{"colleague_name":"Roger","answer":"Vid årsskiftet."}'

    set_tools_completer(complete)
    try:
        reply = await complete_text_with_company_tools(
            [{"role": "user", "content": "När gäller regeln?"}],
            allowed_tools=frozenset({"ask_expert"}),
            consult_tool_handler=handle,
        )
    finally:
        set_tools_completer(None)

    assert reply == "Roger har svarat."
    assert handled == [{"question": "När gäller regeln?"}]


@pytest.mark.asyncio
async def test_tool_loop_dispatches_ask_expert_when_model_only_promises():
    calls = 0
    handled: list[dict[str, Any]] = []

    async def complete(_messages, tools):
        nonlocal calls
        calls += 1
        assert [tool["function"]["name"] for tool in tools or []] == ["ask_expert"]
        if calls == 1:
            return SimpleNamespace(
                content="Jag skickar frågan till kollegan.",
                tool_calls=None,
            )
        return SimpleNamespace(content="Roger har svarat.", tool_calls=None)

    async def handle(arguments):
        handled.append(arguments)
        return '{"colleague_name":"Roger","answer":"Vid årsskiftet."}'

    set_tools_completer(complete)
    try:
        reply = await complete_text_with_company_tools(
            [{"role": "user", "content": "När gäller regeln?"}],
            allowed_tools=frozenset({"ask_expert"}),
            consult_tool_handler=handle,
        )
    finally:
        set_tools_completer(None)

    assert reply == "Roger har svarat."
    assert handled == [{"question": "När gäller regeln?"}]


@pytest.mark.asyncio
async def test_tool_loop_does_not_treat_ordinary_reply_as_consult():
    handled: list[dict[str, Any]] = []

    async def complete(_messages, _tools):
        return SimpleNamespace(
            content="Det kan jag svara på själv: tre år.",
            tool_calls=None,
        )

    async def handle(arguments):
        handled.append(arguments)
        return '{"colleague_name":"Roger","answer":"Vid årsskiftet."}'

    set_tools_completer(complete)
    try:
        reply = await complete_text_with_company_tools(
            [{"role": "user", "content": "Hur lång är preskriptionstiden?"}],
            allowed_tools=frozenset({"ask_expert"}),
            consult_tool_handler=handle,
        )
    finally:
        set_tools_completer(None)

    assert reply == "Det kan jag svara på själv: tre år."
    assert handled == []


def test_consult_handler_uses_default_tools_when_stored_tools_are_none():
    asker = _expert("legacy-tools", "Anna Andersson", "Kommunikation")
    asker.tools = None
    handler = consult_handler_for_persona(
        None,  # type: ignore[arg-type]
        persona=asker,
        mode="interview",
        prompts=default_prompts("sv"),
    )
    assert handler is not None


def test_consult_handler_stays_off_when_ask_expert_is_disabled():
    asker = _expert("no-consult", "Anna Andersson", "Kommunikation")
    asker.tools = ["search_wiki"]
    handler = consult_handler_for_persona(
        None,  # type: ignore[arg-type]
        persona=asker,
        mode="interview",
        prompts=default_prompts("sv"),
    )
    assert handler is None


@pytest.mark.asyncio
async def test_consult_persists_colleague_message_memories_and_broadcasts(
    client_db,
    monkeypatch,
):
    _client, factory = client_db
    memory = RecordingMemory()
    set_expert_memory_factory(lambda: memory)

    async def assess(slot, _config, _prompts):
        return ExpertCompetency(
            has_domain_competence=slot.label == "Roger Björnsson",
            competence_score=90 if slot.label == "Roger Björnsson" else 0,
            competence_reason=(
                "Relevant specialist"
                if slot.label == "Roger Björnsson"
                else "Saknar domänkompetens"
            ),
        )

    async def answer(*_args, **_kwargs):
        assert _kwargs["tools"] == []
        return "Regeln gäller från och med årsskiftet."

    async def no_evidence(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(
        "app.services.expert_consult.assess_expert_competency",
        assess,
    )
    monkeypatch.setattr("app.services.expert_consult.reply_as_persona", answer)
    monkeypatch.setattr(
        "app.services.expert_consult.reusable_expert_chat_evidence_context",
        no_evidence,
    )

    events: list[dict[str, Any]] = []

    async def receive(event: dict[str, Any]) -> None:
        events.append(event)

    await library_chat_broadcast.subscribe_customer(1, receive)
    try:
        async with factory() as session:
            asker = _expert("consult-asker", "Daniel Nilsson", "Kommunikation")
            colleague = _expert("consult-colleague", "Roger Björnsson", "Skatterätt")
            session.add_all([asker, colleague])
            await session.commit()

            handler = expert_consult_handler_for_chat(
                session,
                asker=asker,
                mode="interview",
                prompts=default_prompts("sv"),
            )
            tool_result = await handler(
                {"question": "När börjar den nya skatteregeln gälla?"}
            )

            rows = list(
                (
                    await session.execute(
                        select(PersonaMessage).where(
                            PersonaMessage.persona_id == colleague.id
                        )
                    )
                ).scalars()
            )
    finally:
        await library_chat_broadcast.unsubscribe(receive)

    assert len(rows) == 1
    assert rows[0].role == "assistant"
    assert "Daniel Nilsson frågade mig" in rows[0].content
    assert "Roger Björnsson" in tool_result
    assert {row["source"] for row in memory.adds} == {"expert_consult"}
    assert len(memory.adds) == 2
    assert [event["type"] for event in events] == [
        "thread.message",
        "consult.answered",
    ]


@pytest.mark.asyncio
async def test_consult_refuses_when_asker_has_competence(client_db, monkeypatch):
    _client, factory = client_db

    async def competent(*_args, **_kwargs):
        return ExpertCompetency(
            has_domain_competence=True,
            competence_score=80,
            competence_reason="Relevant specialist",
        )

    monkeypatch.setattr(
        "app.services.expert_consult.assess_expert_competency",
        competent,
    )

    async with factory() as session:
        asker = _expert("competent-asker", "Anna Andersson", "Arbetsrätt")
        session.add(asker)
        await session.commit()
        handler = expert_consult_handler_for_chat(
            session,
            asker=asker,
            mode="interview",
            prompts=default_prompts("sv"),
        )
        with pytest.raises(ValueError, match="själv kompetens"):
            await handler({"question": "Vad gäller enligt arbetsrätten?"})


@pytest.mark.asyncio
async def test_consult_reports_when_no_colleague_matches(client_db, monkeypatch):
    _client, factory = client_db

    async def not_competent(*_args, **_kwargs):
        return ExpertCompetency(
            has_domain_competence=False,
            competence_score=0,
            competence_reason="Saknar domänkompetens",
        )

    monkeypatch.setattr(
        "app.services.expert_consult.assess_expert_competency",
        not_competent,
    )

    async with factory() as session:
        asker = _expert("unmatched-asker", "Karin Karlsson", "Kommunikation")
        session.add(asker)
        await session.commit()
        handler = expert_consult_handler_for_chat(
            session,
            asker=asker,
            mode="interview",
            prompts=default_prompts("sv"),
        )
        with pytest.raises(ValueError, match="Ingen annan expert"):
            await handler({"question": "En mycket smal specialistfråga"})
