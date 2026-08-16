"""Spinndoktor chat: REST history, context builder, WebSocket scope."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")

from app.config import settings
from app.database.base import Base
from app.database.session import get_session
from app.llm import set_text_streamer
from app.main import create_app
from app.services import jobs as jobs_service
from app.services.prompt_store import ensure_default_configurations
from app.services.spindoctor_chat import (
    clear_spindoctor_messages,
    list_spindoctor_messages,
    stream_spindoctor_chat_turn,
)
from app.services.spindoctor_context import (
    _confidence_notes,
    _thresholds_from_ssr_doc,
    build_spindoctor_context,
)
from app.services.report.metrics import compute_report_metrics
from app.services.report.thresholds import default_report_thresholds
from tests.test_verdict_calibration import _generate_report


@pytest.mark.asyncio
async def test_spindoctor_messages_rest(client, tmp_path, monkeypatch):
    report_id = await _generate_report(client, tmp_path, monkeypatch)

    empty = await client.get("/spindoctor/messages", params={"report_id": report_id})
    assert empty.status_code == 200
    assert empty.json() == []

    async def _mock_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "Engagemanget "
        yield "ser spritt ut. [[ref:mottagande]]"

    set_text_streamer(_mock_stream)
    try:
        factory = jobs_service.job_session_factory()
        async with factory() as db:
            stream = stream_spindoctor_chat_turn(
                db,
                report_id=report_id,
                locale="sv",
                message="Hur såg mottagandet ut?",
            )
            done = None
            async for item in stream:
                if not isinstance(item, str):
                    done = item
            assert done is not None
            assert "[[ref:mottagande]]" in done.reply
    finally:
        set_text_streamer(None)

    listed = await client.get("/spindoctor/messages", params={"report_id": report_id})
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"

    deleted = await client.delete("/spindoctor/messages", params={"report_id": report_id})
    assert deleted.status_code == 204

    after = await client.get("/spindoctor/messages", params={"report_id": report_id})
    assert after.json() == []


@pytest.mark.asyncio
async def test_build_spindoctor_context_includes_style_shares(client, tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from app.services.report import ARTIFACT_ROOT

    report_id = await _generate_report(client, tmp_path, monkeypatch)
    ssr_path = Path(ARTIFACT_ROOT) / report_id / "report.ssr.json"
    ssr_doc = json.loads(ssr_path.read_text(encoding="utf-8"))
    bundle = ssr_doc["bundles"][0]
    top_style = max(bundle["style_shares"], key=lambda row: row["share"])["style"]

    factory = jobs_service.job_session_factory()
    async with factory() as db:
        _report, context = await build_spindoctor_context(db, report_id=report_id)
    assert "budskapsstil" in context
    assert top_style in context or top_style.replace("_", " ") in context


@pytest.mark.asyncio
async def test_clear_waits_for_in_flight_turn(client, tmp_path, monkeypatch):
    """Clear must not run until an in-flight turn releases the per-report lock."""
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    gate = asyncio.Event()
    release = asyncio.Event()
    clear_done = asyncio.Event()

    async def _slow_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        gate.set()
        await release.wait()
        yield "Svar efter clear-försök."

    clear_done = asyncio.Event()

    set_text_streamer(_slow_stream)
    try:
        factory = jobs_service.job_session_factory()

        async def _turn() -> None:
            async with factory() as db:
                async for _item in stream_spindoctor_chat_turn(
                    db,
                    report_id=report_id,
                    locale="sv",
                    message="Fråga under pågående svar",
                ):
                    pass

        async def _clear() -> None:
            async with factory() as db:
                await clear_spindoctor_messages(db, report_id)
            clear_done.set()

        turn_task = asyncio.create_task(_turn())
        await gate.wait()
        clear_task = asyncio.create_task(_clear())
        await asyncio.sleep(0.05)
        assert not clear_done.is_set()
        release.set()
        await asyncio.gather(turn_task, clear_task)
        assert clear_done.is_set()
    finally:
        set_text_streamer(None)


@pytest.mark.asyncio
async def test_build_spindoctor_context(client, tmp_path, monkeypatch):
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    factory = jobs_service.job_session_factory()
    async with factory() as db:
        _report, context = await build_spindoctor_context(db, report_id=report_id)
    assert "Population" in context
    assert "SSR" not in context
    assert "Gini" not in context
    assert "mottagande" in context


def test_thresholds_from_ssr_doc_uses_frozen_snapshot():
    custom = default_report_thresholds().model_copy(
        update={
            "verdict": default_report_thresholds().verdict.model_copy(
                update={"pos_strong": 0.35}
            )
        }
    )
    loaded = _thresholds_from_ssr_doc(
        {"report_thresholds": custom.model_dump(mode="json")}
    )
    assert loaded.verdict.pos_strong == 0.35


def test_confidence_notes_respect_frozen_thresholds():
    from app.services.report.bundles import RunBundle
    from app.services.report.classify import BundleClassification

    tone = {
        "Starkt negativ": 0.0,
        "Något negativ": 0.1,
        "Neutral": 0.5,
        "Något positiv": 0.3,
        "Starkt positiv": 0.1,
    }
    clf = BundleClassification(
        topic_shares={"Test": 1.0},
        tone_shares=tone,
        tone_mode="ssr",
    )
    bundle = RunBundle(
        label="A",
        run_id=1,
        run_name="T",
        attempt_id="att",
        seed="1",
        engine="none",
        posts=[{"post_id": 1, "user_id": 1, "content": "test", "num_likes": 5}],
        comments=[],
        injection_texts=["test"],
        ticks_run=1,
    )
    metrics = compute_report_metrics([bundle], [clf])
    default_notes = _confidence_notes(
        metrics,
        [bundle],
        locale="sv",
        thresholds=default_report_thresholds(),
    )
    custom = default_report_thresholds().model_copy(
        update={
            "verdict": default_report_thresholds().verdict.model_copy(
                update={"pos_strong": 0.35}
            )
        }
    )
    custom_notes = _confidence_notes(
        metrics,
        [bundle],
        locale="sv",
        thresholds=custom,
    )
    assert custom_notes != default_notes
    assert "35%" in custom_notes[0]
    assert "30%" in default_notes[0]


def test_ws_rejects_unknown_scope():
    settings.deepseek_api_key = "test-key-not-real"
    app = create_app()

    async def _session_override():
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as s:
            await ensure_default_configurations(s)
            yield s
        await engine.dispose()

    app.dependency_overrides[get_session] = _session_override
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "hello", "scope": "unknown"})
            msg = ws.receive_json()
            assert msg["type"] == "error"


@pytest.mark.asyncio
async def test_list_clear_service():
    from app.database.models import Report, SpindoctorMessage
    from app.serializers import utcnow

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        report = Report(
            id="rpt_spin_test",
            status="succeeded",
            title="Test",
            locale="sv",
            mode="quick",
            sources=[{"run_id": 1, "attempt_id": "att_x"}],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(report)
        session.add(
            SpindoctorMessage(report_id=report.id, role="user", content="Hej")
        )
        await session.commit()

        rows = await list_spindoctor_messages(session, report.id)
        assert len(rows) == 1
        await clear_spindoctor_messages(session, report.id)
        rows = await list_spindoctor_messages(session, report.id)
        assert rows == []
    await engine.dispose()
