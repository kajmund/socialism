"""Parallel expert tools, failure marking, and connection release."""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database.base import Base
from app.database.models import Job, Kund, Persona, SmeExpertTurn, UserAccount
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.expert_async_tools import PlannedCall, ToolWork, run_tool_calls
from app.services.expert_chat_research_tool import research_tool_handler_for_chat
from app.services.expert_turn_cancel import bind_turn_cancel
from app.services.prompt_store import ensure_default_configurations
from app.services.sme_expert_turns import execute_expert_turn


def _work(*names: str) -> ToolWork:
    return ToolWork(
        persona_id="expert",
        mode="interview",
        actor_user_id="user",
        history=[],
        user_message="jämför",
        calls=tuple(PlannedCall(str(index), name, {}) for index, name in enumerate(names)),
    )


async def test_independent_tools_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()

    async def run_one(call, _work):
        if call.name == "slow":
            await asyncio.wait_for(started.wait(), timeout=1)
            return "slow"
        started.set()
        return "fast"

    monkeypatch.setattr("app.services.expert_async_tools._run_one", run_one)
    blob, results = await asyncio.wait_for(run_tool_calls(_work("slow", "fast")), timeout=1)
    assert results == ("slow", "fast")
    assert "slow" in blob and "fast" in blob


async def test_tool_timeout_is_not_ordinary_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "expert_tool_timeout_seconds", 0.05)

    async def run_one(_call, _work):
        await asyncio.sleep(30)
        return "borde inte synas"

    monkeypatch.setattr("app.services.expert_async_tools._run_one", run_one)
    work = _work("lookup_company")
    _blob, results = await run_tool_calls(work)
    assert results == ("TOOL_FAILED lookup_company: verktyget misslyckades (timeout).",)
    assert work.failed_calls == 1


async def test_tool_exception_is_marked_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run_one(_call, _work):
        raise ValueError("persona missing")

    monkeypatch.setattr("app.services.expert_async_tools._run_one", run_one)
    work = _work("lookup_company")
    _blob, results = await run_tool_calls(work)
    assert results[0].startswith("TOOL_FAILED lookup_company:")
    assert "persona missing" not in results[0]
    assert work.failed_calls == 1


async def test_turn_cancel_stops_waiting_for_a_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    cancel = asyncio.Event()

    async def run_one(_call, _work):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.services.expert_async_tools._run_one", run_one)

    async def run() -> None:
        with bind_turn_cancel(cancel):
            await run_tool_calls(_work("lookup_company"))

    task = asyncio.create_task(run())
    await asyncio.wait_for(started.wait(), timeout=1)
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)


async def test_session_factory_is_resolved_once_per_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    original = jobs_service.job_session_factory

    def counting():
        seen.append("factory")
        return original()

    monkeypatch.setattr("app.services.expert_async_tools.job_session_factory", counting)

    async def run_one(_call, _work):
        return "ok"

    monkeypatch.setattr("app.services.expert_async_tools._run_one", run_one)
    await run_tool_calls(_work("search", "lookup_company"))
    assert seen == ["factory"]


async def test_research_enqueue_releases_the_only_connection(tmp_path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'research.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.4,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    probed = asyncio.Event()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(Kund(name="Acme", slug="acme", available_modules=["dd"]))
            await session.flush()
            customer_id = (await session.scalars(select(Kund.id))).one()
            expert = Persona(
                id="expert-1",
                customer_id=customer_id,
                kind="expert",
                name="Jurist",
                age=None,
                occ="Jurist",
                district="—",
                quote="",
                origin="test",
                profile={},
                tools=None,
            )
            session.add(expert)
            await session.commit()

            def enqueue(job_id: str) -> None:
                async def probe() -> None:
                    async with factory() as other:
                        assert await other.get(Job, job_id) is not None
                    probed.set()

                asyncio.get_running_loop().create_task(probe())

            jobs_service.set_schedule_hook(enqueue)
            handler = research_tool_handler_for_chat(
                session,
                persona=expert,
                history=[("user", "Undersök klausulen", None)],
                user_message="Undersök klausulen",
            )
            result = await handler({"question": "Vilka rekvisit gäller?"})
            await asyncio.wait_for(probed.wait(), timeout=1)
            assert not session.in_transaction()
        assert "köat" in result
    finally:
        jobs_service.set_schedule_hook(None)
        await engine.dispose()


async def test_expert_turn_releases_connection_during_the_model_call(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'turn.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.4,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    release = asyncio.Event()
    probed = asyncio.Event()

    async def stream_text(*_args, **_kwargs):
        async with factory() as probe:
            assert await probe.scalar(select(Persona.id)) == "e-turn"
        probed.set()
        await release.wait()
        yield "Klart."

    monkeypatch.setattr(settings, "expert_reasoning_route_enabled", False)
    monkeypatch.setattr(
        "app.services.persona_chat.schedule_expert_memory_update",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr("app.llm.chat.stream_text", stream_text)
    monkeypatch.setattr(
        "app.services.sme_expert_turns.expert_turn_heartbeat_seconds",
        lambda: 3600,
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            await ensure_default_configurations(session)
            session.add(UserAccount(id="user-1", email="user@example.com", role="user", kund_id=1))
            session.add(
                Persona(
                    id="e-turn",
                    customer_id=1,
                    kind="expert",
                    name="Jurist",
                    age=40,
                    occ="Jurist",
                    district="Stockholm",
                    profile={"name": "Jurist"},
                    tools=[],
                )
            )
            now = utcnow()
            session.add(
                SmeExpertTurn(
                    request_id="req-voice",
                    customer_id=1,
                    user_id="user-1",
                    persona_id="e-turn",
                    message="Vad gäller?",
                    status="running",
                    fence=1,
                    lease_token="token",
                    lease_expires_at=now + timedelta(minutes=5),
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
        pending = asyncio.create_task(
            execute_expert_turn(
                factory,
                request_id="req-voice",
                persona_id="e-turn",
                message="Vad gäller?",
                image_sha256=None,
                fence=1,
                token="token",
            )
        )
        try:
            await asyncio.wait_for(probed.wait(), timeout=2)
        except TimeoutError:
            release.set()
            await pending
            raise
        release.set()
        done = await asyncio.wait_for(pending, timeout=2)
        assert done.reply == "Klart."
    finally:
        if not release.is_set():
            release.set()
        await engine.dispose()


def test_research_prompt_migration_drops_the_confirmation_turn() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/166_research_same_turn.py"
    spec = importlib.util.spec_from_file_location("research_same_turn", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT, "
                "default_sv TEXT, default_en TEXT, default_nb TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE prompt_overrides (prompt_field_id INTEGER, language TEXT, text TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO prompt_fields (id, key, default_sv, default_en, default_nb) "
                "VALUES (1, :key, :sv, :en, :sv)"
            ),
            {"key": migration._RESEARCH_KEY, **migration._RESEARCH_OLD},
        )
        connection.execute(
            sa.text(
                "INSERT INTO prompt_fields (id, key, default_sv, default_en, default_nb) "
                "VALUES (2, :key, :sv, :en, :sv)"
            ),
            {
                "key": migration._VOICE_KEY,
                "sv": f"Inledning. {migration._VOICE_OLD['sv']} Avslut.",
                "en": f"Intro. {migration._VOICE_OLD['en']} End.",
            },
        )
        migration.op.get_bind = lambda: connection
        migration.upgrade()
        stored = connection.execute(
            sa.text("SELECT default_sv FROM prompt_fields WHERE key = :key"),
            {"key": migration._RESEARCH_KEY},
        ).scalar_one()
        voice = connection.execute(
            sa.text("SELECT default_sv, default_en FROM prompt_fields WHERE key = :key"),
            {"key": migration._VOICE_KEY},
        ).one()
    assert "bekräftat" not in stored
    assert "samma svar" in stored
    assert migration._VOICE_NEW["sv"] in voice[0]
    assert migration._VOICE_NEW["en"] in voice[1]
    engine.dispose()
