"""Spinndoktor DD report context and tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Report
from app.serializers import utcnow
from app.services.spindoctor_context import build_spindoctor_context, load_spindoctor_source
from app.services.spindoctor_dd import (
    average_scores_by_sub_question,
    build_dd_spindoctor_context_block,
    load_dd_report_json,
)
from app.services.spindoctor_mcp_tools import SpindoctorToolContext, run_spindoctor_mcp_tool
from app.services.spindoctor_tools import run_spindoctor_tool
from tests.test_dd_report import _sample_result


def _dd_doc() -> dict:
    return _sample_result().model_dump(mode="json")


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


async def _seed_dd_report(session: AsyncSession, tmp_path: Path, report_id: str = "rpt_dd") -> str:
    out_dir = tmp_path / report_id
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = _dd_doc()
    doc["mode"] = "dd"
    (out_dir / "report.dd.json").write_text(json.dumps(doc), encoding="utf-8")

    now = utcnow()
    session.add(
        Report(
            id=report_id,
            customer_id=1,
            status="succeeded",
            title="DD Spinndoktor",
            locale="sv",
            mode="dd",
            sources=[
                {
                    "type": "dd_session",
                    "session_id": "panel_test",
                    "candidate_id": "cand_1",
                }
            ],
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    return report_id


def test_average_scores_by_sub_question():
    doc = _dd_doc()
    from app.services.spindoctor_dd import sub_questions_from_dd_doc

    rows = average_scores_by_sub_question(doc, sub_questions_from_dd_doc(doc))
    assert len(rows) == 3
    by_id = {row["sub_question_id"]: row["value"] for row in rows}
    assert by_id["finansiell_halsa"] == 8.0
    assert by_id["legal_risk"] == 4.0
    assert by_id["marknadsposition"] == 6.0


def test_build_dd_spindoctor_context_block_includes_candidate_and_radar_hint():
    doc = _dd_doc()
    context = build_dd_spindoctor_context_block(doc, locale="sv", title="DD Test")
    assert "Testbolaget AB" in context
    assert "Finansiell hälsa" in context
    assert "radar" in context
    assert "get_report_dd" in context


@pytest.mark.asyncio
async def test_load_dd_report_json(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.spindoctor_dd.ARTIFACT_ROOT", str(tmp_path))
    out_dir = tmp_path / "rpt_x"
    out_dir.mkdir()
    doc = _dd_doc()
    (out_dir / "report.dd.json").write_text(json.dumps(doc), encoding="utf-8")
    loaded = load_dd_report_json("rpt_x")
    assert loaded is not None
    assert loaded["candidate"]["namn"] == "Testbolaget AB"


@pytest.mark.asyncio
async def test_build_spindoctor_context_for_dd_report(session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.spindoctor_dd.ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.services.spindoctor_context.ARTIFACT_ROOT", str(tmp_path))
    report_id = await _seed_dd_report(session, tmp_path)

    report, context = await build_spindoctor_context(session, report_id=report_id)
    assert report.mode == "dd"
    assert "Testbolaget AB" in context
    assert "Medelpoäng per delfråga" in context
    assert "Körning" not in context


@pytest.mark.asyncio
async def test_load_spindoctor_source_dd_has_empty_bundles(session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.spindoctor_dd.ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.services.spindoctor_context.ARTIFACT_ROOT", str(tmp_path))
    report_id = await _seed_dd_report(session, tmp_path)

    report, bundles = await load_spindoctor_source(session, report_id=report_id)
    assert report.mode == "dd"
    assert bundles == []


@pytest.mark.asyncio
async def test_oasis_tool_returns_guard_on_dd_report(session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.spindoctor_dd.ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.services.spindoctor_context.ARTIFACT_ROOT", str(tmp_path))
    report_id = await _seed_dd_report(session, tmp_path)

    result = await run_spindoctor_tool(
        session,
        "get_run",
        {},
        report_id=report_id,
    )
    assert "OASIS" in result
    assert "get_report_dd" in result


@pytest.mark.asyncio
async def test_get_report_dd_mcp_tool(session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.spindoctor_mcp_tools.ARTIFACT_ROOT", str(tmp_path))
    report_id = await _seed_dd_report(session, tmp_path)

    raw = await run_spindoctor_mcp_tool(
        session,
        "get_report_dd",
        {"report_id": report_id},
        ctx=SpindoctorToolContext(report_id=report_id, module_id="dd"),
    )
    payload = json.loads(raw)
    assert payload["candidate"]["namn"] == "Testbolaget AB"
    assert len(payload["scores"]) == 3


@pytest.mark.asyncio
async def test_render_radar_chart_emits_widget(session):
    ctx = SpindoctorToolContext(report_id="rpt_dd", module_id="dd")
    result = await run_spindoctor_mcp_tool(
        session,
        "render_chart",
        {
            "chart_type": "radar",
            "title": "DD-poäng",
            "series": [
                {"label": "Finansiell hälsa", "value": 8},
                {"label": "Legal risk", "value": 4},
                {"label": "Marknadsposition", "value": 6},
            ],
        },
        ctx=ctx,
    )
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["chart_type"] == "radar"
    assert len(ctx.widgets) == 1
    assert ctx.widgets[0].chart_type == "radar"


@pytest.mark.asyncio
async def test_render_radar_rejects_out_of_range(session):
    ctx = SpindoctorToolContext(report_id="rpt_dd", module_id="dd")
    with pytest.raises(ValueError, match="between 0 and 10"):
        await run_spindoctor_mcp_tool(
            session,
            "render_chart",
            {
                "chart_type": "radar",
                "title": "Fel",
                "series": [{"label": "X", "value": 11}],
            },
            ctx=ctx,
        )
