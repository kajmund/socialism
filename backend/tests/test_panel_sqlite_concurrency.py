"""Panel turn commits must not hold SQLite write locks across LLM calls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.tokens import mint_access_token, user_from_bearer_token
from app.config import settings
from app.database.base import Base
from app.database.models import PanelSession, UserAccount
from app.database.sqlite import (
    SQLITE_BUSY_TIMEOUT_MS,
    async_engine_kwargs,
    register_sqlite_pragmas,
)
from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services.panel.competency import ExpertCompetency
from app.services.panel.engine import run_generic_panel
from app.services.panel.research import empty_research_structured
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.synthesis import GenericPanelSynthesis
from app.services.prompt_catalog import default_prompts

USER_ID = "00000000-0000-4000-8000-dddddddddddd"


def _config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        topic="Vad är rekvisiten för dråp vid självförsvar?",
        brief="Straffrättslig fråga.",
        max_rounds=1,
        expert_slots=[
            PanelExpertSlot(
                slot_id="crime",
                label="Straffrättsjurist",
                profile="Straffrätt",
            )
        ],
    )


@pytest.fixture
async def file_sessions(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/panel-concurrency.sqlite"
    engine = create_async_engine(url, **async_engine_kwargs(url))
    register_sqlite_pragmas(engine, url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(
            UserAccount(
                id=USER_ID,
                email="concurrent@example.com",
                role="admin",
                kund_id=None,
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_file_uses_wal_and_busy_timeout(file_sessions):
    async with file_sessions() as session:
        journal = (await session.execute(text("PRAGMA journal_mode"))).scalar_one()
        foreign_keys = (await session.execute(text("PRAGMA foreign_keys"))).scalar_one()
        busy = (await session.execute(text("PRAGMA busy_timeout"))).scalar_one()
    assert str(journal).lower() == "wal"
    assert int(foreign_keys) == 1
    assert int(busy) == SQLITE_BUSY_TIMEOUT_MS


@pytest.mark.asyncio
async def test_panel_llm_pause_allows_auth_read_and_independent_write(file_sessions):
    opened = asyncio.Event()
    release = asyncio.Event()
    settings.supabase_jwt_secret = "test-supabase-jwt-secret-not-real"

    async def complete_text(messages, *, model=None):
        user = messages[-1]["content"]
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen till panelen."
        if "JA eller NEJ" in user or "YES or NO" in user:
            opened.set()
            await release.wait()
            return "NEJ"
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys."
        return "Svar"

    async def complete_tools(messages, tools=None):
        return SimpleNamespace(content=await complete_text(messages), tool_calls=None)

    async def complete_structured(messages, response_model):
        if response_model is ExpertCompetency:
            return ExpertCompetency(
                has_domain_competence=True,
                competence_reason="Straffrätt.",
            )
        empty = empty_research_structured(response_model)
        if empty is not None:
            return empty
        if response_model is GenericPanelSynthesis:
            return GenericPanelSynthesis(summary="Lucka.", claims=[], unanswered=[])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(complete_text)
    set_tools_completer(complete_tools)
    set_structured_completer(complete_structured)

    async with file_sessions() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=_config()))
        await db.commit()
        panel_id = created.id

    async def run_panel() -> None:
        async with file_sessions() as db:
            row = await get_panel_session(db, panel_id)
            assert row is not None
            await run_generic_panel(
                db, row, default_prompts("sv"), frozen_evidence=True
            )

    task = asyncio.create_task(run_panel())
    await asyncio.wait_for(opened.wait(), timeout=5)

    async with file_sessions() as reader:
        row = await reader.get(PanelSession, panel_id)
        assert row is not None
        phases = [turn["phase"] for turn in (row.transcript or [])]
        assert "opening" in phases
        token = mint_access_token(user_id=USER_ID, email="concurrent@example.com")
        try:
            account = await user_from_bearer_token(reader, token)
        except OperationalError as exc:
            raise AssertionError("authenticated read hit a locked database") from exc
        assert account.id == USER_ID
        listed = (await reader.execute(select(PanelSession))).scalars().all()
        assert any(item.id == panel_id for item in listed)

    async with file_sessions() as writer:
        writer.add(
            PanelSession(
                id="panel_independent_write",
                protocol="generic_panel",
                status="draft",
                config={"protocol": "generic_panel", "topic": "Oberoende skrivning"},
                transcript=[],
                scratchpads={},
            )
        )
        try:
            await writer.commit()
        except OperationalError as exc:
            raise AssertionError("independent write hit a locked database") from exc

    async with file_sessions() as check:
        other = await check.get(PanelSession, "panel_independent_write")
        assert other is not None

    release.set()
    await asyncio.wait_for(task, timeout=5)
    async with file_sessions() as db:
        finished = await get_panel_session(db, panel_id)
    assert finished is not None
    assert finished.status == "succeeded"
