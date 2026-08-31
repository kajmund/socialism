"""Regression: parallel Spinndoktor tool calls must not corrupt shared AsyncSession."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona, PersonaMessage, Population, Run
from app.llm import set_text_streamer
from app.serializers import utcnow
from app.services.prompt_store import ensure_default_configurations
from app.services import jobs as jobs_service
from app.services.spindoctor_chat import _run_spindoctor_tool_loop
from app.services.spindoctor_mcp_tools import SpindoctorToolContext


def _variant_payload(*personas: tuple[str, str]) -> dict:
    agents = [
        {
            "index": i,
            "username": f"user{i}",
            "member_name": name,
            "persona_id": pid,
            "role": "population",
        }
        for i, (pid, name) in enumerate(personas)
    ]
    return {
        "id": "main",
        "label": "Huvudtidslinje",
        "ticks_run": 2,
        "agents": agents,
        "tick_markers": [
            {"tick_index": 0, "day": 1, "silent": False, "key": "t1", "time_end": 10},
            {"tick_index": 1, "day": 2, "silent": False, "key": "t2", "time_end": 20},
        ],
        "posts": [],
        "comments": [],
        "trace": [],
    }


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    jobs_service.set_job_session_factory(factory)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        await ensure_default_configurations(db)
        now = utcnow()
        for pid, name in [("p-a", "Anna Andersson"), ("p-b", "Bertil Bengtsson")]:
            db.add(
                Persona(
                    id=pid,
                    customer_id=1,
                    name=name,
                    age=40,
                    occ="Ekonom",
                    district="Centrum",
                    quote="",
                    origin="manuell",
                    profile={"name": name, "age": "40"},
                    updated_at=now,
                )
            )
        db.add(Population(id=1, name="Testpop", size=2, recipe={}, fingerprint=[]))
        db.add(
            Run(
                id=7,
                project_id=1,
                name="Testkörning",
                status="done",
                population_id=1,
                seed="s",
                main_ticks=[],
                branch={},
                oasis_options={},
                results={
                    "attempts": [
                        {
                            "id": "att_1",
                            "variants": [
                                _variant_payload(
                                    ("p-a", "Anna Andersson"),
                                    ("p-b", "Bertil Bengtsson"),
                                )
                            ],
                        }
                    ]
                },
                updated_at=now,
            )
        )
        await db.commit()
        yield db
    jobs_service.set_job_session_factory(None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_parallel_start_interview_persists_all_messages(session, monkeypatch):
    """Two parallel start_interview opening turns must not lose PersonaMessage rows."""

    replies = {"Anna": "Svar Anna", "Bertil": "Svar Bertil"}

    async def _stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        user = next(
            (m["content"] for m in reversed(_messages) if m.get("role") == "user"),
            "",
        )
        await asyncio.sleep(0.03)
        if "Anna" in user:
            yield replies["Anna"]
        else:
            yield replies["Bertil"]

    set_text_streamer(_stream)

    class FakeCall:
        def __init__(self, call_id: str, name: str, arguments: dict) -> None:
            self.id = call_id

            class Fn:
                pass

            self.function = Fn()
            self.function.name = name
            self.function.arguments = json.dumps(arguments)

    class FakeMessage:
        def __init__(self) -> None:
            self.content = ""
            self.tool_calls = [
                FakeCall(
                    "call_a",
                    "start_interview",
                    {
                        "persona_name": "Anna",
                        "opening_question": "Fråga till Anna?",
                    },
                ),
                FakeCall(
                    "call_b",
                    "start_interview",
                    {
                        "persona_name": "Bertil",
                        "opening_question": "Fråga till Bertil?",
                    },
                ),
            ]

    round_count = 0

    async def fake_complete(_messages, _tools):
        nonlocal round_count
        round_count += 1
        if round_count == 1:
            return FakeMessage()
        empty = FakeMessage()
        empty.tool_calls = None
        return empty

    monkeypatch.setattr(
        "app.services.spindoctor_chat.complete_with_tools",
        fake_complete,
    )

    from app.database.models import Report

    session.add(
        Report(
            id="rpt_parallel",
            customer_id=1,
            status="succeeded",
            title="Parallel",
            locale="sv",
            mode="quick",
            sources=[{"run_id": 7, "attempt_id": "att_1"}],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    await session.commit()
    ctx = SpindoctorToolContext(report_id="rpt_parallel", module_id="politik")

    try:
        working, _widgets = await _run_spindoctor_tool_loop(
            session,
            [{"role": "system", "content": "test"}],
            ctx=ctx,
        )
    finally:
        set_text_streamer(None)

    tool_messages = [row for row in working if row.get("role") == "tool"]
    assert len(tool_messages) == 2, tool_messages
    for row in tool_messages:
        payload = json.loads(str(row["content"]))
        assert payload.get("ok") is True, row["content"]

    rows = (
        await session.execute(
            select(PersonaMessage).order_by(PersonaMessage.id.asc())
        )
    ).scalars().all()
    user_rows = [row for row in rows if row.role == "user"]
    assistant_rows = [row for row in rows if row.role == "assistant"]
    assert len(user_rows) == 2
    assert len(assistant_rows) == 2
    assert {row.content for row in user_rows} == {
        "Fråga till Anna?",
        "Fråga till Bertil?",
    }
    assert {row.content for row in assistant_rows} == set(replies.values())
