"""Spinndoktor MCP tools and widget events."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona, PersonaMessage, Population, Report, Run
from app.schemas.domain import PersonaChatResponse, PersonaMessageOut
from app.serializers import utcnow
from app.services.spindoctor_mcp_tools import (
    SpindoctorToolContext,
    run_spindoctor_mcp_tool,
    spindoctor_mcp_tool_specs,
)


def _variant_payload(persona_id: str) -> dict:
    return {
        "id": "main",
        "label": "Huvudtidslinje",
        "ticks_run": 2,
        "agents": [
            {
                "index": 0,
                "username": "johan",
                "member_name": "Johan Lindqvist",
                "persona_id": persona_id,
                "role": "population",
            }
        ],
        "tick_markers": [
            {"tick_index": 0, "day": 1, "silent": False, "key": "t1"},
            {"tick_index": 1, "day": 2, "silent": False, "key": "t2"},
        ],
        "posts": [{"post_id": 1, "user_id": 0, "content": "Nyhet", "created_at": 5}],
        "comments": [],
        "trace": [],
    }


from app.services.kund_store import ensure_default_kunder


async def _seed_interview_report(session: AsyncSession) -> tuple[str, str]:
    await ensure_default_kunder(session)
    now = utcnow()
    persona = Persona(
        id="p-johan",
        customer_id=1,
        name="Johan Lindqvist",
        age=44,
        occ="Ekonom",
        district="Centrum",
        quote="",
        origin="manuell",
        profile={"name": "Johan Lindqvist", "age": "44"},
        updated_at=now,
    )
    pop = Population(id=1, name="Testpop", size=1, recipe={}, fingerprint=[])
    run = Run(
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
                    "variants": [_variant_payload("p-johan")],
                }
            ]
        },
        updated_at=now,
    )
    report = Report(
        id="rpt_interview",
        status="succeeded",
        title="Intervjurapport",
        locale="sv",
        mode="quick",
        sources=[{"run_id": 7, "attempt_id": "att_1"}],
        created_at=now,
        updated_at=now,
    )
    session.add(persona)
    session.add(pop)
    session.add(run)
    session.add(report)
    await session.commit()
    return "rpt_interview", "p-johan"


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()


def test_spindoctor_mcp_tool_specs_include_widgets_and_search():
    names = {
        spec["function"]["name"]
        for spec in spindoctor_mcp_tool_specs()
        if isinstance(spec, dict)
    }
    assert "render_chart" in names
    assert "place_note" in names
    assert "start_interview" in names
    assert "ask_interview_question" in names
    assert "read_interview_transcript" in names
    assert "search_wiki" in names
    assert "search_duckduckgo" in names
    assert "scb_search_tables" in names
    assert "list_runs" in names
    assert "list_reports" in names
    assert "list_populations" in names
    assert "get_report_dd" in names


@pytest.mark.asyncio
async def test_render_chart_emits_widget(session):
    ctx = SpindoctorToolContext(report_id="rpt_x")
    result = await run_spindoctor_mcp_tool(
        session,
        "render_chart",
        {
            "chart_type": "hbar",
            "title": "Ton",
            "series": [{"label": "Positiv", "value": 0.42}],
        },
        ctx=ctx,
    )
    assert "widget_id" in result
    assert len(ctx.widgets) == 1
    assert ctx.widgets[0].kind == "chart"
    assert ctx.widgets[0].chart_type == "hbar"


@pytest.mark.asyncio
async def test_place_note_emits_widget(session):
    ctx = SpindoctorToolContext(report_id="rpt_x")
    await run_spindoctor_mcp_tool(
        session,
        "place_note",
        {"title": "Slutsats", "body": "Mottagandet är blandat."},
        ctx=ctx,
    )
    assert len(ctx.widgets) == 1
    assert ctx.widgets[0].kind == "note"
    assert ctx.widgets[0].body == "Mottagandet är blandat."


@pytest.mark.asyncio
async def test_list_runs_reports_populations(session):
    now = utcnow()
    session.add(Population(id=1, name="Testpop", size=3, recipe={}, fingerprint=[]))
    session.add(
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
            updated_at=now,
        )
    )
    session.add(
        Report(
            id="rpt_list",
            status="succeeded",
            title="Lista",
            locale="sv",
            mode="quick",
            sources=[],
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()

    runs = await run_spindoctor_mcp_tool(session, "list_runs", {}, ctx=SpindoctorToolContext())
    reports = await run_spindoctor_mcp_tool(
        session, "list_reports", {}, ctx=SpindoctorToolContext()
    )
    pops = await run_spindoctor_mcp_tool(
        session, "list_populations", {}, ctx=SpindoctorToolContext()
    )
    assert "Testkörning" in runs
    assert "rpt_list" in reports
    assert "Testpop" in pops


@pytest.mark.asyncio
async def test_start_interview_emits_widget(session):
    report_id, persona_id = await _seed_interview_report(session)
    ctx = SpindoctorToolContext(report_id=report_id)
    result = await run_spindoctor_mcp_tool(
        session,
        "start_interview",
        {"persona_name": "Johan Lindqvist"},
        ctx=ctx,
    )
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["persona_id"] == persona_id
    assert payload["through_tick_index"] == 1
    assert len(ctx.widgets) == 1
    widget = ctx.widgets[0]
    assert widget.kind == "interview"
    assert widget.persona_name == "Johan Lindqvist"
    assert widget.run_id == 7
    assert widget.attempt_id == "att_1"
    assert widget.variant_id == "main"


@pytest.mark.asyncio
async def test_start_interview_opening_question(session, monkeypatch):
    report_id, persona_id = await _seed_interview_report(session)
    ctx = SpindoctorToolContext(report_id=report_id)

    async def fake_turn(_session, **kwargs):
        assert kwargs["asked_by"] == "doctor"
        assert kwargs["message"] == "Vad tycker du om förslaget?"
        assert kwargs["persona_id"] == persona_id
        return PersonaChatResponse(
            reply="Jag är tveksam.",
            messages=[
                PersonaMessageOut(
                    id=1,
                    mode="interview",
                    role="user",
                    content=kwargs["message"],
                    created_at="",
                    asked_by="doctor",
                ),
                PersonaMessageOut(
                    id=2,
                    mode="interview",
                    role="assistant",
                    content="Jag är tveksam.",
                    created_at="",
                ),
            ],
        )

    monkeypatch.setattr(
        "app.services.spindoctor_mcp_tools.complete_run_interview_turn",
        fake_turn,
    )

    result = json.loads(
        await run_spindoctor_mcp_tool(
            session,
            "start_interview",
            {
                "persona_name": "Johan Lindqvist",
                "opening_question": "Vad tycker du om förslaget?",
            },
            ctx=ctx,
        )
    )
    assert result["ok"] is True
    assert result["opening_question"] == "Vad tycker du om förslaget?"
    assert result["answer"] == "Jag är tveksam."


@pytest.mark.asyncio
async def test_ask_interview_question(session, monkeypatch):
    report_id, persona_id = await _seed_interview_report(session)
    ctx = SpindoctorToolContext(report_id=report_id)
    start = json.loads(
        await run_spindoctor_mcp_tool(
            session,
            "start_interview",
            {"persona_name": "Johan"},
            ctx=ctx,
        )
    )

    async def fake_turn(_session, **kwargs):
        assert kwargs["asked_by"] == "doctor"
        assert kwargs["message"] == "Varför då?"
        return PersonaChatResponse(reply="För att kostnaden känns oklar.", messages=[])

    monkeypatch.setattr(
        "app.services.spindoctor_mcp_tools.complete_run_interview_turn",
        fake_turn,
    )

    result = json.loads(
        await run_spindoctor_mcp_tool(
            session,
            "ask_interview_question",
            {
                "widget_id": start["widget_id"],
                "question": "Varför då?",
            },
            ctx=ctx,
        )
    )
    assert result["ok"] is True
    assert result["question"] == "Varför då?"
    assert result["answer"] == "För att kostnaden känns oklar."
    assert result["persona_id"] == persona_id


@pytest.mark.asyncio
async def test_read_interview_transcript_by_widget_id(session):
    report_id, persona_id = await _seed_interview_report(session)
    ctx = SpindoctorToolContext(report_id=report_id)
    start = json.loads(
        await run_spindoctor_mcp_tool(
            session,
            "start_interview",
            {"persona_name": "Johan"},
            ctx=ctx,
        )
    )
    session.add(
        PersonaMessage(
            persona_id=persona_id,
            mode="interview",
            role="user",
            content="Litar du på finansieringen?",
            run_id=7,
            attempt_id="att_1",
            variant_id="main",
            through_tick_index=start["through_tick_index"],
            asked_by="doctor",
            created_at=utcnow(),
        )
    )
    session.add(
        PersonaMessage(
            persona_id=persona_id,
            mode="interview",
            role="assistant",
            content="Jag är skeptisk tills jag ser detaljerna.",
            run_id=7,
            attempt_id="att_1",
            variant_id="main",
            through_tick_index=start["through_tick_index"],
            created_at=utcnow(),
        )
    )
    await session.commit()

    transcript = json.loads(
        await run_spindoctor_mcp_tool(
            session,
            "read_interview_transcript",
            {"widget_id": start["widget_id"]},
            ctx=ctx,
        )
    )
    assert len(transcript["messages"]) == 2
    assert transcript["messages"][0]["content"] == "Litar du på finansieringen?"
    assert transcript["messages"][0]["asked_by"] == "doctor"
    assert "skeptisk" in transcript["messages"][1]["content"]


@pytest.mark.asyncio
async def test_read_interview_transcript_by_coordinates(session):
    report_id, persona_id = await _seed_interview_report(session)
    session.add(
        PersonaMessage(
            persona_id=persona_id,
            mode="interview",
            role="user",
            content="Hej",
            run_id=7,
            attempt_id="att_1",
            variant_id="main",
            through_tick_index=1,
            created_at=utcnow(),
        )
    )
    await session.commit()

    transcript = json.loads(
        await run_spindoctor_mcp_tool(
            session,
            "read_interview_transcript",
            {
                "persona_id": persona_id,
                "run_id": 7,
                "attempt_id": "att_1",
                "variant_id": "main",
                "through_tick_index": 1,
            },
            ctx=SpindoctorToolContext(report_id=report_id),
        )
    )
    assert len(transcript["messages"]) == 1
    assert transcript["messages"][0]["content"] == "Hej"
