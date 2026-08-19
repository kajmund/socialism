"""Spinndoktor MCP tools and widget events."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Population, Report, Run
from app.serializers import utcnow
from app.services.spindoctor_mcp_tools import (
    SpindoctorToolContext,
    run_spindoctor_mcp_tool,
    spindoctor_mcp_tool_specs,
)


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
    assert "search_wiki" in names
    assert "search_duckduckgo" in names
    assert "scb_search_tables" in names
    assert "list_runs" in names
    assert "list_reports" in names
    assert "list_populations" in names


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
