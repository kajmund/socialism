"""Exact workspace reuse. No semantic cache and no extra model call."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    Job,
    Kund,
    UserAccount,
)
from app.database.workspaces import Workspace, WorkspaceChat, WorkspaceChatMessage
from app.services.document_qa import AnswerPostWrite, QaWrite, SourceCite, Viewer
from app.services.document_qa.from_workspace import (
    workspace_analysis_contract,
    workspace_question,
)
from app.services.document_qa.store import persist
from app.services.document_qa.tenants import TenantCatalogs, set_tenant_catalogs
from app.services.document_qa.workspace_reuse import (
    exact_hit_for_question,
    try_reuse_workspace_answer,
)
from app.services.knowledge.units import hash_text
from app.services.workspace_research_job import run_workspace_research_job

DIM = 8
STAMP = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
REUSE = Path(__file__).resolve().parents[1] / "app/services/document_qa/workspace_reuse.py"
PERSIST = Path(__file__).resolve().parents[1] / "app/services/document_qa/from_workspace.py"


def test_reuse_stays_out_of_the_persist_module():
    persist_src = PERSIST.read_text()
    reuse_src = REUSE.read_text()
    assert "exact_reuse" not in persist_src
    assert "semantic_candidates" not in persist_src
    assert "semantic_candidates" not in reuse_src
    assert "TenantCatalogs" not in persist_src


def _write() -> QaWrite:
    return QaWrite(
        question_text="Vad gäller uppsägning?",
        document_id="doc-1",
        document_version_id="ver-1",
        workspace_id="ws-1",
        contract=workspace_analysis_contract(),
        status="ANSWERED",
        answer_text="Svar om uppsägning.",
        posts=(AnswerPostWrite("Svar om uppsägning.", (SourceCite("unit-1", "Paragraf 12"),)),),
        asked_at="2026-10-11T10:00:00Z",
        created_at="2026-10-11T10:00:00Z",
    )


def _job(**request):
    payload = {
        "chat_id": "chat-1",
        "workspace_id": "ws-1",
        "question": "Vad gäller uppsägning?",
        "document_manifest": [{
            "source_object_id": "obj-1",
            "document_id": "doc-1",
            "document_version_id": "ver-1",
            "workspace_id": "ws-1",
        }],
    }
    payload.update(request)
    return Job(
        id="job-reuse-1",
        customer_id=1,
        kind="workspace_research",
        status="pending",
        label="Vad gäller uppsägning?",
        created_at=STAMP,
        request=payload,
    )


@pytest.fixture
def catalogs(tmp_path):
    registry = TenantCatalogs(tmp_path, dimension=DIM)
    set_tenant_catalogs(registry)
    try:
        yield registry
    finally:
        set_tenant_catalogs(None)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/qa-reuse.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _seed_chat(session):
    session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
    await session.flush()
    session.add(UserAccount(id="user-1", email="one@test.local", role="user", kund_id=1))
    session.add(Workspace(id="ws-1", customer_id=1, name="Byrån", kind="company"))
    session.add(WorkspaceChat(
        id="chat-1", customer_id=1, workspace_id="ws-1",
        owner_user_id="user-1", module="dd", title="",
    ))
    session.add(CanonicalDocumentRecord(
        id="doc-1", scope_type="customer", scope_key="customer:1",
        customer_id=1, source_type="upload", canonical_uri="doc://doc-1",
        title="Avtal", extra={},
    ))
    session.add(DocumentVersionRecord(
        id="ver-1", scope_type="customer", scope_key="customer:1",
        customer_id=1, document_id="doc-1", content_hash=hash_text("body"),
        mime_type="text/plain", extra={},
    ))


def test_answered_retrieved_evidence_is_an_exact_hit(catalogs):
    persist(catalogs.open_for(1), Viewer(
        customer_id=1, workspace_id="ws-1",
        readable_document_ids=frozenset({"doc-1"}),
        readable_version_ids=frozenset({"ver-1"}),
    ), _write())
    hit = exact_hit_for_question(catalogs.open_for(1), workspace_question(_job()))
    assert hit is not None and hit.reuse == "exact"
    assert hit.answer.text == "Svar om uppsägning."
    assert hit.answer.review_status == "unreviewed"


def test_not_found_retrieved_evidence_is_not_reused(catalogs):
    persist(catalogs.open_for(1), Viewer(
        customer_id=1, workspace_id="ws-1",
        readable_document_ids=frozenset({"doc-1"}),
        readable_version_ids=frozenset({"ver-1"}),
    ), QaWrite(
        question_text="Finns karens?",
        document_id="doc-1",
        document_version_id="ver-1",
        workspace_id="ws-1",
        contract=workspace_analysis_contract(),
        status="NOT_FOUND",
        answer_text="Hittades inte i undersökt material.",
        posts=(AnswerPostWrite("Hittades inte.", (SourceCite("unit-1", "Ingen karens"),)),),
        asked_at="2026-10-11T10:00:00Z",
        created_at="2026-10-11T10:00:00Z",
    ))
    job = _job(question="Finns karens?")
    assert exact_hit_for_question(catalogs.open_for(1), workspace_question(job)) is None


@pytest.mark.asyncio
async def test_try_reuse_delivers_without_research(factory, catalogs):
    persist(catalogs.open_for(1), Viewer(
        customer_id=1, workspace_id="ws-1",
        readable_document_ids=frozenset({"doc-1"}),
        readable_version_ids=frozenset({"ver-1"}),
    ), _write())
    async with factory() as session:
        await _seed_chat(session)
        session.add(_job())
        await session.commit()
        result = await try_reuse_workspace_answer(session, "job-reuse-1")
    assert result is not None
    assert result["reuse"] == "exact"
    assert result["answer"] == "Svar om uppsägning."
    assert result["citations"][0]["text_unit_id"] == "unit-1"
    async with factory() as session:
        job = await session.get(Job, "job-reuse-1")
        assert job.result["reuse"] == "exact"
        message = await session.scalar(
            select(WorkspaceChatMessage).where(WorkspaceChatMessage.job_id == "job-reuse-1")
        )
        assert message.content == "Svar om uppsägning."


@pytest.mark.asyncio
async def test_try_reuse_skips_when_owner_is_missing(factory):
    async with factory() as session:
        await _seed_chat(session)
        session.add(_job())
        await session.commit()
        assert await try_reuse_workspace_answer(session, "job-reuse-1") is None


@pytest.mark.asyncio
async def test_research_job_returns_reuse_and_skips_prepare(factory, monkeypatch):
    async def fake_reuse(session, job_id):
        return {"answer": "Cachat svar.", "reuse": "exact", "citations": []}

    async def boom(*_args, **_kwargs):
        raise AssertionError("research must not run after an exact hit")

    monkeypatch.setattr(
        "app.services.workspace_research_job.try_reuse_workspace_answer", fake_reuse,
    )
    monkeypatch.setattr("app.services.workspace_research_job._prepare", boom)
    result = await run_workspace_research_job(factory, job_id="ignored")
    assert result == {"answer": "Cachat svar.", "reuse": "exact", "citations": []}
