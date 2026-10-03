from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, Persona, PersonaMessage
from app.services.kund_store import bolag_demo_customer_id
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
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.consult_competence import rank_consult_competence
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

    async def rank(question, experts, jev=None):
        del question, jev
        return {
            expert_id: 0.9 if expert_id == "consult-colleague" else 0.1
            for expert_id, _profile in experts
        }

    async def answer(*_args, **_kwargs):
        assert _kwargs["tools"] == []
        return "Regeln gäller från och med årsskiftet."

    async def no_evidence(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(
        "app.services.expert_consult.rank_consult_competence",
        rank,
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

    async def rank(question, experts, jev=None):
        del question, jev
        return {expert_id: 0.9 for expert_id, _profile in experts}

    monkeypatch.setattr(
        "app.services.expert_consult.rank_consult_competence",
        rank,
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

    async def rank(question, experts, jev=None):
        del question, jev
        return {expert_id: 0.1 for expert_id, _profile in experts}

    monkeypatch.setattr(
        "app.services.expert_consult.rank_consult_competence",
        rank,
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


@pytest.mark.asyncio
async def test_consult_assesses_each_colleague_when_more_than_six(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'consult.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    memory = RecordingMemory()
    set_expert_memory_factory(lambda: memory)
    seen: list[list[str]] = []

    async def rank(question, experts, jev=None):
        del question, jev
        seen.append([expert_id for expert_id, _profile in experts])
        async with factory() as probe:
            assert await probe.scalar(select(Persona.id).limit(1))
        return {
            expert_id: 0.9 if expert_id == "wide-7" else 0.1
            for expert_id, _profile in experts
        }

    async def answer(*_args, **kwargs):
        async with factory() as probe:
            assert await probe.scalar(select(Persona.id).limit(1))
        assert kwargs["tools"] == []
        return "Integrationen är den svåra delen."

    monkeypatch.setattr("app.services.expert_consult.rank_consult_competence", rank)
    monkeypatch.setattr("app.services.expert_consult.reply_as_persona", answer)
    monkeypatch.setattr(
        "app.services.expert_consult.reusable_expert_chat_evidence_context",
        lambda *_args, **_kwargs: _empty_evidence(),
    )

    try:
        async with factory() as session:
            session.add(Kund(id=1, name="acme", slug="acme", available_modules=["dd"]))
            asker = _expert("wide-asker", "Josef Larsson", "Avtal")
            colleagues = [
                _expert(f"wide-{index}", f"Kollega {index}", "Integration")
                for index in range(1, 8)
            ]
            session.add_all([asker, *colleagues])
            await session.commit()
            handler = expert_consult_handler_for_chat(
                session,
                asker=asker,
                mode="interview",
                prompts=default_prompts("sv"),
            )
            tool_result = await handler(
                {"question": "Vilka svårigheter uppstår vid operativa integrationer?"}
            )
    finally:
        await engine.dispose()

    assert seen == [["wide-asker", *[f"wide-{index}" for index in range(1, 8)]]]
    assert "Kollega 7" in tool_result


@pytest.mark.asyncio
async def test_consult_asks_only_experts_on_the_same_customer(client_db, monkeypatch):
    _client, factory = client_db
    seen: list[list[str]] = []

    async def rank(question, experts, jev=None):
        del question, jev
        seen.append([expert_id for expert_id, _profile in experts])
        return {
            expert_id: 0.9 if expert_id == "same-colleague" else 0.1
            for expert_id, _profile in experts
        }

    async def answer(*_args, **kwargs):
        assert kwargs["tools"] == []
        return "Samma kund svarade."

    monkeypatch.setattr("app.services.expert_consult.rank_consult_competence", rank)
    monkeypatch.setattr("app.services.expert_consult.reply_as_persona", answer)
    monkeypatch.setattr(
        "app.services.expert_consult.reusable_expert_chat_evidence_context",
        lambda *_args, **_kwargs: _empty_evidence(),
    )
    set_expert_memory_factory(lambda: RecordingMemory())

    async with factory() as session:
        other_customer_id = await bolag_demo_customer_id(session)
        asker = _expert("same-asker", "Josef Larsson", "Avtal")
        colleague = _expert("same-colleague", "Daniel Andersson", "Integration")
        outsider = _expert("other-customer", "Anton Hansson", "Integration")
        outsider.customer_id = other_customer_id
        session.add_all([asker, colleague, outsider])
        await session.commit()
        handler = expert_consult_handler_for_chat(
            session,
            asker=asker,
            mode="interview",
            prompts=default_prompts("sv"),
        )
        tool_result = await handler({"question": "Hur bedöms en operativ integration?"})

    assert seen
    assert "same-colleague" in seen[0]
    assert "other-customer" not in seen[0]
    assert "Daniel Andersson" in tool_result


@pytest.mark.asyncio
async def test_consult_jev_failure_reaches_the_caller(client_db, monkeypatch):
    _client, factory = client_db

    async def rank(*_args, **_kwargs):
        raise JevClientError("Jev request timed out", category="timeout")

    async def answer(*_args, **_kwargs):
        raise AssertionError("colleague reply must not run")

    monkeypatch.setattr("app.services.expert_consult.rank_consult_competence", rank)
    monkeypatch.setattr("app.services.expert_consult.reply_as_persona", answer)

    async with factory() as session:
        asker = _expert("jev-fail-asker", "Anna Andersson", "Avtal")
        session.add(asker)
        await session.commit()
        handler = expert_consult_handler_for_chat(
            session,
            asker=asker,
            mode="interview",
            prompts=default_prompts("sv"),
        )
        with pytest.raises(JevClientError, match="timed out"):
            await handler({"question": "En integrationsfråga"})


@pytest.mark.asyncio
async def test_rank_consult_competence_reads_one_noul_per_expert():
    class RecordingJev:
        def __init__(self) -> None:
            self.state: dict[str, Any] | None = None
            self.questions: dict[str, Any] | None = None

        async def ask(self, *, state, questions, model, timeout_seconds):
            self.state = state
            self.questions = questions
            assert model
            assert timeout_seconds > 0
            return JevSystemOneResult(
                answers={key: {"noul": 0.8 if key == "a" else 0.2} for key in questions},
                model=model,
                latency_ms=1,
                input_chars=1,
                usage=JevUsage(),
                raw={},
            )

    jev = RecordingJev()
    scores = await rank_consult_competence(
        question="Vilka integrationssvårigheter finns?",
        experts=(("a", "Integrationsledare"), ("b", "Straffrättsjurist")),
        jev=jev,
    )

    assert scores == {"a": 0.8, "b": 0.2}
    assert jev.state is not None
    assert jev.state["question"] == "Vilka integrationssvårigheter finns?"
    assert [row["id"] for row in jev.state["experts"]] == ["a", "b"]
    assert jev.questions is not None
    assert jev.questions["a"]["type"] == "noul"
    assert jev.questions["b"]["type"] == "noul"


async def _empty_evidence() -> str:
    return ""
