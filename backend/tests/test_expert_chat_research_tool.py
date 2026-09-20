from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Job, Kund, Persona
from app.llm import set_tools_completer
from app.services import jobs as jobs_service
from app.services.dd.company_mcp import complete_text_with_company_tools
from app.services.expert_tools import default_expert_tools
from app.services.persona_chat import research_tool_handler_for_chat


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        customer = Kund(name="Acme", slug="acme", available_modules=["dd"])
        db.add(customer)
        await db.flush()
        expert = Persona(
            id="expert-1",
            customer_id=customer.id,
            kind="expert",
            name="Avtalsjuristen",
            age=None,
            occ="Jurist",
            district="—",
            quote="",
            origin="test",
            profile={},
            tools=None,
        )
        db.add(expert)
        await db.flush()
        yield db, expert, factory
    jobs_service.set_schedule_hook(None)
    jobs_service.set_job_session_factory(None)
    await engine.dispose()


async def test_research_tool_refuses_without_prior_offer_and_confirmation(session):
    db, expert, _factory = session
    handler = research_tool_handler_for_chat(
        db,
        persona=expert,
        history=[],
        user_message="Undersök frågan",
    )

    result = await handler({"question": "Vilka rekvisit gäller?"})

    assert "startades inte" in result
    jobs = list((await db.execute(select(Job))).scalars())
    assert jobs == []


async def test_research_tool_does_not_treat_a_question_about_research_as_consent(session):
    db, expert, _factory = session
    handler = research_tool_handler_for_chat(
        db,
        persona=expert,
        history=[("assistant", "Vad menar du med research?", None)],
        user_message="Ja",
    )

    result = await handler({"question": "Vilka rekvisit gäller?"})

    assert "startades inte" in result
    jobs = list((await db.execute(select(Job))).scalars())
    assert jobs == []


async def test_research_tool_queues_one_background_job_after_explicit_confirmation(session):
    db, expert, _factory = session
    scheduled: list[str] = []
    jobs_service.set_schedule_hook(scheduled.append)
    handler = research_tool_handler_for_chat(
        db,
        persona=expert,
        history=[
            ("user", "Vad innebär klausul 2?", None),
            (
                "assistant",
                "Underlaget räcker inte. Vill du att jag startar research?",
                None,
            )
        ],
        user_message="Ja, gör det",
    )

    first = await handler(
        {"question": "Vilka rekvisit krävs för jämkning enligt 36 § avtalslagen?"}
    )
    second = await handler(
        {"question": "Vilka rekvisit krävs för jämkning enligt 36 § avtalslagen?"}
    )

    job = (await db.execute(select(Job))).scalar_one()
    assert job.kind == "expert_chat_research"
    assert job.customer_id == expert.customer_id
    assert job.request["persona_id"] == expert.id
    assert job.request["specific_question"] == "Vad innebär klausul 2?"
    assert scheduled == [job.id]
    assert job.id in first
    assert "redan köat" in second


async def test_research_tool_accepts_explicit_spoken_confirmation_without_punctuation(
    session,
):
    db, expert, _factory = session
    scheduled: list[str] = []
    jobs_service.set_schedule_hook(scheduled.append)
    handler = research_tool_handler_for_chat(
        db,
        persona=expert,
        history=[
            ("user", "Hur ser konkurrensen ut?", None),
            (
                "assistant",
                "Vill du att jag startar en bakgrundsresearch om konkurrenssituationen",
                None,
            ),
        ],
        user_message=(
            "Ja, du får starta en bakgrundsresearch för att få en bättre bild"
        ),
    )

    result = await handler({"question": "Hur ser Devbrains konkurrenssituation ut?"})

    job = (await db.execute(select(Job))).scalar_one()
    assert job.kind == "expert_chat_research"
    assert scheduled == [job.id]
    assert job.id in result


async def test_research_tool_rejects_spoken_confirmation_with_negation(session):
    db, expert, _factory = session
    handler = research_tool_handler_for_chat(
        db,
        persona=expert,
        history=[
            (
                "assistant",
                "Vill du att jag startar en bakgrundsresearch om konkurrenssituationen",
                None,
            ),
        ],
        user_message="Ja, men starta inte research ännu",
    )

    result = await handler({"question": "Hur ser Devbrains konkurrenssituation ut?"})

    assert "startades inte" in result
    jobs = list((await db.execute(select(Job))).scalars())
    assert jobs == []


async def test_queued_research_runs_as_a_background_job(session, monkeypatch):
    db, expert, factory = session
    scheduled: list[str] = []
    jobs_service.set_schedule_hook(scheduled.append)
    jobs_service.set_job_session_factory(factory)
    handler = research_tool_handler_for_chat(
        db,
        persona=expert,
        history=[
            ("user", "Vad innebär klausul 2?", None),
            ("assistant", "Ska jag starta research?", None),
        ],
        user_message="Ja",
    )
    await handler({"question": "Vilka rekvisit gäller?"})
    job = (await db.execute(select(Job))).scalar_one()

    async def fake_runner(_factory, *, job_id: str):
        assert job_id == job.id
        return {"attempt_id": "attempt-1", "completed_questions": 1}

    monkeypatch.setattr(
        "app.services.expert_chat_research.run_expert_chat_research_job",
        fake_runner,
    )

    await jobs_service._run_job(job.id)

    async with factory() as check:
        completed = await check.get(Job, job.id)
        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.result == {
            "attempt_id": "attempt-1",
            "completed_questions": 1,
        }


def test_research_tool_is_available_to_default_experts():
    assert "start_research" in default_expert_tools()


async def test_native_research_tool_dispatches_without_company_tools():
    calls = 0
    handled: list[dict[str, str]] = []

    async def complete(_messages, tools=None):
        nonlocal calls
        calls += 1
        names = [tool["function"]["name"] for tool in tools or []]
        assert names == ["start_research"]
        if calls == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(
                        id="call-1",
                        function=SimpleNamespace(
                            name="start_research",
                            arguments='{"question":"Vilka rekvisit gäller?"}',
                        ),
                    )
                ],
            )
        return SimpleNamespace(content="Researchjobbet är köat.", tool_calls=None)

    async def handle(arguments):
        handled.append(arguments)
        return "Köat i bakgrunden."

    set_tools_completer(complete)
    try:
        reply = await complete_text_with_company_tools(
            [{"role": "user", "content": "Ja"}],
            allowed_tools=frozenset({"start_research"}),
            research_tool_handler=handle,
        )
    finally:
        set_tools_completer(None)

    assert reply == "Researchjobbet är köat."
    assert handled == [{"question": "Vilka rekvisit gäller?"}]
