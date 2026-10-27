"""Live-speech session scope reads per-expert correction settings while the session is open."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.live_speech import _scope
from app.config import settings
from app.database.base import Base
from app.database.models import Kund, Persona, UserAccount
from app.database.workspace_models import VoiceWorkspace
from app.database.workspaces import WorkspaceChat
from app.schemas.live_speech import SessionStart
from app.serializers import utcnow
from app.services.prompt_defaults import dd_prompt_defaults
from app.services.prompt_fields_store import ensure_prompt_field_defaults
from app.services.workspaces import ensure_company_workspace


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/scope.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _seed(factory) -> None:
    async with factory.begin() as session:
        session.add(Kund(id=1, name="C1", slug="c1", available_modules=[], product="sme"))
        session.add(UserAccount(id="user-1", email="a@test.local", role="user", kund_id=1))
        common = await ensure_company_workspace(session, customer_id=1)
        session.add(WorkspaceChat(
            id="chat-1", customer_id=1, workspace_id=common.id,
            owner_user_id="user-1", module="dd", title="T",
        ))
        session.add(VoiceWorkspace(
            id="canvas-1", workspace_id=common.id, chat_id="chat-1",
            customer_id=1, owner_user_id="user-1", creation_key="scope",
            creation_payload_hash="0" * 64, title="T", module="dd", state={},
        ))
        session.add_all([
            Persona(
                id="expert-1", customer_id=1, kind="expert", name="E", occ="Jurist",
                district="Göteborg", quote="", origin="manuell", profile={}, tools=None,
                live_voice_provider="socialism", live_voice="voice",
                stt_correction_enabled=False, stt_correction_timeout_seconds=3.5,
                updated_at=utcnow(),
            ),
            Persona(
                id="expert-2", customer_id=1, kind="expert", name="F", occ="Jurist",
                district="Göteborg", quote="", origin="manuell", profile={}, tools=None,
                live_voice_provider="socialism", live_voice="voice",
                updated_at=utcnow(),
            ),
        ])
        await ensure_prompt_field_defaults(session, "dd", dd_prompt_defaults())


def _start(expert_id: str) -> SessionStart:
    return SessionStart(
        type="session.start",
        workspace_id="canvas-1",
        expert_id=expert_id,
        language="sv",
        client_request_id="probe",
    )


@pytest.mark.asyncio
async def test_scope_reads_expert_correction_settings_before_session_closes(factory, monkeypatch):
    await _seed(factory)
    monkeypatch.setattr(
        "app.api.live_speech.jobs_service.job_session_factory", lambda: factory,
    )
    async with factory() as session:
        user = await session.get(UserAccount, "user-1")
        scope = await _scope(_start("expert-1"), user)
    assert scope.correction_enabled is False
    assert scope.correction_timeout == 3.5


@pytest.mark.asyncio
async def test_scope_uses_process_defaults_when_unset(factory, monkeypatch):
    await _seed(factory)
    monkeypatch.setattr(
        "app.api.live_speech.jobs_service.job_session_factory", lambda: factory,
    )
    monkeypatch.setattr(settings, "live_speech_correction_default_enabled", True)
    monkeypatch.setattr(settings, "live_speech_correction_default_timeout_seconds", 4.0)
    async with factory() as session:
        user = await session.get(UserAccount, "user-1")
        scope = await _scope(_start("expert-2"), user)
    assert scope.correction_enabled is True
    assert scope.correction_timeout == 4.0
