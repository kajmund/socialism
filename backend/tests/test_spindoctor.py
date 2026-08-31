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
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-jwt-secret-not-real")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-supabase-service-role-not-real")

from app.config import settings
from app.database.base import Base
from app.database.models import Report, Run, UserAccount
from app.database.session import get_session
from app.llm import set_text_streamer, set_tools_completer
from app.main import create_app
from app.services import jobs as jobs_service
from app.services.prompt_store import ensure_default_configurations
from app.services.spindoctor_chat import (
    clear_spindoctor_messages,
    list_spindoctor_messages,
    stream_spindoctor_chat_turn,
)
from app.services.spindoctor_context import build_spindoctor_context
from app.services.spindoctor_politik import (
    _confidence_notes,
    _thresholds_from_ssr_doc,
)
from app.services.spindoctor_tools import run_spindoctor_tool
from app.services.report.metrics import compute_report_metrics
from app.services.report.thresholds import default_report_thresholds
from tests.conftest import ADMIN_USER_ID, TEST_JWT_SECRET, mint_access_token
from tests.test_verdict_calibration import _generate_report


class _NoToolMessage:
    content = ""
    tool_calls = None


async def _no_tools(_messages: list[dict[str, object]], _tools: list | None = None):
    return _NoToolMessage()


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
    set_tools_completer(_no_tools)
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
        set_tools_completer(None)

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
async def test_spindoctor_widgets_board_rest(client, tmp_path, monkeypatch):
    from app.schemas.domain import SpindoctorWidgetOut
    from app.services.spindoctor_board import save_spindoctor_widget

    report_id = await _generate_report(client, tmp_path, monkeypatch)
    empty = await client.get("/spindoctor/widgets", params={"report_id": report_id})
    assert empty.status_code == 200
    assert empty.json() == []

    factory = jobs_service.job_session_factory()
    async with factory() as db:
        first = await save_spindoctor_widget(
            db,
            report_id,
            SpindoctorWidgetOut(
                id="wdg_note1",
                kind="note",
                title="Anteckning",
                created_at="2026-08-21T10:00:00+00:00",
                body="Mottagandet är splittrat.",
            ),
        )
        second = await save_spindoctor_widget(
            db,
            report_id,
            SpindoctorWidgetOut(
                id="wdg_note2",
                kind="note",
                title="Andra",
                created_at="2026-08-21T10:01:00+00:00",
                body="Nästa kort.",
            ),
        )
        assert first.pos_x != second.pos_x or first.pos_y != second.pos_y

    listed = await client.get("/spindoctor/widgets", params={"report_id": report_id})
    assert listed.status_code == 200
    rows = listed.json()
    assert [row["id"] for row in rows] == ["wdg_note1", "wdg_note2"]

    moved = await client.patch(
        "/spindoctor/widgets/wdg_note1",
        json={"report_id": report_id, "pos_x": 12.5, "pos_y": 40},
    )
    assert moved.status_code == 200
    assert moved.json()["pos_x"] == 12.5
    assert moved.json()["pos_y"] == 40

    removed = await client.delete(
        "/spindoctor/widgets/wdg_note1",
        params={"report_id": report_id},
    )
    assert removed.status_code == 204
    after_one = await client.get("/spindoctor/widgets", params={"report_id": report_id})
    assert [row["id"] for row in after_one.json()] == ["wdg_note2"]

    cleared = await client.delete("/spindoctor/widgets", params={"report_id": report_id})
    assert cleared.status_code == 204
    after = await client.get("/spindoctor/widgets", params={"report_id": report_id})
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
    set_tools_completer(_no_tools)
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
        set_tools_completer(None)


@pytest.mark.asyncio
async def test_build_spindoctor_context(client, tmp_path, monkeypatch):
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    factory = jobs_service.job_session_factory()
    async with factory() as db:
        _report, context = await build_spindoctor_context(db, report_id=report_id)
    assert "Population" in context
    assert "Körning" in context
    assert "Rapportrun" in context
    assert "Testbudskap" not in context
    assert "Äldreomsorg och hemtjänst" not in context
    assert "SSR" not in context
    assert "Gini" not in context
    assert "mottagande" in context


async def _put_injection(session, report_id: str, text: str) -> None:
    report = await session.get(Report, report_id)
    assert report is not None
    run = await session.get(Run, int(report.sources[0]["run_id"]))
    assert run is not None
    run.main_ticks = [
        {
            "key": "d1",
            "day": 1,
            "injections": [
                {
                    "key": "inj1",
                    "type": "party_post",
                    "text": text,
                    "sender": "Partiet",
                }
            ],
        }
    ]
    await session.commit()


@pytest.mark.asyncio
async def test_spindoctor_tools_read_run_data(client, tmp_path, monkeypatch):
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    budskap = "Vi satsar på äldreomsorgen i hela kommunen."
    factory = jobs_service.job_session_factory()
    async with factory() as db:
        await _put_injection(db, report_id, budskap)
        message = await run_spindoctor_tool(
            db, "get_test_message", {}, report_id=report_id
        )
        run = await run_spindoctor_tool(db, "get_run", {}, report_id=report_id)
        hits = await run_spindoctor_tool(
            db,
            "search_reactions",
            {"query": "trafik", "kind": "comment"},
            report_id=report_id,
        )
        actors = await run_spindoctor_tool(db, "list_actors", {}, report_id=report_id)
        citizen = await run_spindoctor_tool(
            db, "get_citizen", {"name": "Anna"}, report_id=report_id
        )
        interviews = await run_spindoctor_tool(
            db, "list_interviews", {}, report_id=report_id
        )
    assert budskap in message
    assert "Rapportrun" in run
    assert "trafik" in hits
    assert "Anna" in actors or "Anna" in citizen
    assert "total" in interviews


@pytest.mark.asyncio
async def test_spindoctor_turn_can_call_get_test_message(
    client, tmp_path, monkeypatch
):
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    budskap = "Vi satsar på äldreomsorgen i hela kommunen."
    factory = jobs_service.job_session_factory()
    async with factory() as db:
        await _put_injection(db, report_id, budskap)

    class _Fn:
        name = "get_test_message"
        arguments = "{}"

    class _Call:
        id = "call_msg"
        function = _Fn()

    class _ToolTurn:
        content = ""
        tool_calls = [_Call()]

    class _Final:
        content = "Budskapet handlar om äldreomsorg. [[ref:mottagande]]"
        tool_calls = None

    seen_tools: list[str] = []
    turns = {"n": 0}

    async def _tools(messages: list[dict[str, object]], tools: list | None = None):
        turns["n"] += 1
        names = [
            spec["function"]["name"]
            for spec in (tools or [])
            if isinstance(spec, dict)
        ]
        seen_tools.extend(names)
        if turns["n"] == 1:
            return _ToolTurn()
        return _Final()

    set_tools_completer(_tools)
    try:
        async with factory() as db:
            done = None
            async for item in stream_spindoctor_chat_turn(
                db,
                report_id=report_id,
                locale="sv",
                message="Vad sa budskapet?",
            ):
                if not isinstance(item, str):
                    done = item
        assert done is not None
        assert "äldreomsorg" in done.reply.lower()
        assert "get_test_message" in seen_tools
    finally:
        set_tools_completer(None)


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
    settings.supabase_jwt_secret = TEST_JWT_SECRET

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            await ensure_default_configurations(session)
            session.add(
                UserAccount(
                    id=ADMIN_USER_ID,
                    email="admin@test.local",
                    role="admin",
                    kund_id=None,
                )
            )
            await session.commit()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_prepare())

    jobs_service.set_job_session_factory(factory)
    app = create_app()

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    token = mint_access_token(sub=ADMIN_USER_ID, email="admin@test.local")
    try:
        with TestClient(app) as tc:
            with tc.websocket_connect(f"/ws/chat?access_token={token}") as ws:
                ws.send_json({"type": "hello", "scope": "unknown"})
                msg = ws.receive_json()
                assert msg["type"] == "error"
    finally:
        jobs_service.set_job_session_factory(None)
        loop.run_until_complete(engine.dispose())
        loop.close()


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
            customer_id=1,
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
