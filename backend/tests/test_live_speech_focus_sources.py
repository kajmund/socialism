"""stt.focus only feeds text from the user's readable org workspaces to the STT."""

import logging

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    Kund,
    StoredObject,
    UserAccount,
)
from app.database.workspace_models import VoiceWorkspace
from app.database.workspaces import WorkspaceChat
from app.schemas.workspace import WorkspaceDocumentTab, WorkspaceState
from app.services import jobs as jobs_service
from app.services.live_speech_runtime import LiveSpeechRuntime, LiveSpeechScope
from app.services.live_speech_stt_terms import (
    keywords_from_text_units,
    readable_focus_source_ids,
    readable_focus_texts,
    shown_source_ids,
)
from app.services.workspaces import create_client_workspace, ensure_company_workspace
from tests.text_unit_fakes import persisted_text_unit


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/focus.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _seed_scope(factory) -> dict[str, str]:
    async with factory.begin() as session:
        session.add(Kund(id=1, name="C1", slug="c1", available_modules=[]))
        await session.flush()
        session.add_all([
            UserAccount(id="user-1", email="a@test.local", role="user", kund_id=1),
            UserAccount(id="user-2", email="b@test.local", role="user", kund_id=1),
        ])
        await session.flush()
        common = await ensure_company_workspace(session, customer_id=1)
        client_b = await create_client_workspace(session, customer_id=1, user_id="user-2", name="B")
        session.add_all([
            StoredObject(
                id="src-a", customer_id=1, workspace_id=common.id, module="dd", kind="document",
                bucket="c1", object_key="src-a", filename="a.pdf",
                content_type="application/pdf", size_bytes=1,
            ),
            StoredObject(
                id="src-b", customer_id=1, workspace_id=client_b.id, module="dd", kind="document",
                bucket="c1", object_key="src-b", filename="b.pdf",
                content_type="application/pdf", size_bytes=1,
            ),
            StoredObject(
                id="src-null", customer_id=1, workspace_id=None, module="dd", kind="document",
                bucket="c1", object_key="src-null", filename="null.pdf",
                content_type="application/pdf", size_bytes=1,
            ),
        ])
        await session.flush()
    return {"common": common.id, "b": client_b.id}


async def _seed_documents(factory, workspace_ids: dict[str, str]) -> None:
    async with factory.begin() as session:
        for document_id, object_id in (("doc-a", "src-a"), ("doc-b", "src-b")):
            session.add(CanonicalDocumentRecord(
                id=document_id,
                scope_type="customer",
                scope_key="customer:1",
                customer_id=1,
                source_object_id=object_id,
                source_type="upload",
                canonical_uri=f"doc://{document_id}",
                title=document_id,
                extra={},
            ))
            session.add(DocumentVersionRecord(
                id=f"ver-{document_id}",
                scope_type="customer",
                scope_key="customer:1",
                customer_id=1,
                document_id=document_id,
                content_hash=f"hash-{document_id}",
                mime_type="text/plain",
            ))
        await session.flush()
        await persisted_text_unit(
            session,
            id="tu-a",
            document_version_id="ver-doc-a",
            document_id="doc-a",
            customer_id=1,
            scope_type="customer",
            scope_key="customer:1",
            section_id=None,
            ordinal=0,
            text="Aktieägaravtalet reglerar uppsägningstid och uppsägningstid igen.",
        )
        await persisted_text_unit(
            session,
            id="tu-b",
            document_version_id="ver-doc-b",
            document_id="doc-b",
            customer_id=1,
            scope_type="customer",
            scope_key="customer:1",
            section_id=None,
            ordinal=0,
            text="Fastighetsbildningsavtal om servitut och servitut.",
        )


async def _seed_canvas(factory, common_id: str) -> str:
    async with factory.begin() as session:
        session.add(WorkspaceChat(
            id="chat-1",
            customer_id=1,
            workspace_id=common_id,
            owner_user_id="user-1",
            module="dd",
            title="T",
        ))
        session.add(VoiceWorkspace(
            id="canvas-1",
            workspace_id=common_id,
            chat_id="chat-1",
            customer_id=1,
            owner_user_id="user-1",
            creation_key="focus",
            creation_payload_hash="0" * 64,
            title="T",
            module="dd",
            state={},
        ))
    return "canvas-1"


@pytest.mark.asyncio
async def test_readable_focus_source_ids_drops_unreadable_and_unknown(factory):
    workspace_ids = await _seed_scope(factory)
    async with factory() as session:
        allowed, dropped = await readable_focus_source_ids(
            session,
            customer_id=1,
            source_ids=["src-a", "src-b", "src-null", "src-missing"],
            workspace_ids=[workspace_ids["common"]],
        )
    assert allowed == ["src-a"]
    assert dropped == ["src-b", "src-null", "src-missing"]


@pytest.mark.asyncio
async def test_focus_sources_excludes_unreadable_text_from_stt(factory, caplog):
    workspace_ids = await _seed_scope(factory)
    await _seed_documents(factory, workspace_ids)
    canvas_id = await _seed_canvas(factory, workspace_ids["common"])

    runtime = LiveSpeechRuntime.__new__(LiveSpeechRuntime)
    runtime.scope = LiveSpeechScope(
        user_id="user-1",
        customer_id=1,
        workspace_id=canvas_id,
        expert_id="expert-1",
        language="sv",
        voice_id="voice-1",
        workspace_state=WorkspaceState(),
        prompts={},
    )
    runtime._base_keywords = []
    updates: list[dict] = []

    class FakeStt:
        async def update(self, **kwargs) -> None:
            updates.append(kwargs)

    runtime._stt = FakeStt()
    jobs_service.set_job_session_factory(factory)
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.live_speech_runtime"):
            await runtime.focus_sources(["src-a", "src-b"])
    finally:
        jobs_service.set_job_session_factory(None)

    assert len(updates) == 1
    keywords = updates[-1]["keywords"]
    folded = {word.casefold() for word in keywords}
    assert "uppsägningstid" in folded
    assert "aktieägaravtalet" in folded
    assert "fastighetsbildningsavtal" not in folded
    assert "servitut" not in folded
    assert "live_speech.focus_source_dropped" in caplog.text
    assert "src-b" in caplog.text


@pytest.mark.asyncio
async def test_session_bootstrap_stt_skips_unreadable_shown_sources(factory):
    """Stale open tabs must not seed STT keywords from a private client workspace."""
    workspace_ids = await _seed_scope(factory)
    await _seed_documents(factory, workspace_ids)
    canvas_id = await _seed_canvas(factory, workspace_ids["common"])
    state = WorkspaceState(
        documents=[WorkspaceDocumentTab(source_id="src-b")],
    )
    async with factory() as session:
        texts, dropped = await readable_focus_texts(
            session,
            customer_id=1,
            user_id="user-1",
            canvas_workspace_id=canvas_id,
            source_ids=shown_source_ids(state),
        )
    assert dropped == ["src-b"]
    keywords = keywords_from_text_units(texts)
    folded = {word.casefold() for word in keywords}
    assert "fastighetsbildningsavtal" not in folded
    assert "servitut" not in folded
