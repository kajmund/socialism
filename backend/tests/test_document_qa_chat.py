"""Persist a finished document-chat answer. Do not reuse a cache hit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database.base import Base
from app.database.graph_v2 import GraphIngestWork
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Job, Kund
from app.services.document_qa.from_workspace import (
    enqueue_workspace_document_answer,
    qa_write_from_seed,
    workspace_qa_seed,
)
from app.services.document_qa.kinds import DOCUMENT_QA_WRITE
from app.services.graph_v2.errors import PermanentGraphError
from app.services.knowledge.units import hash_text

STAMP = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
SOURCE = Path(__file__).resolve().parents[1] / "app/services/document_qa/from_workspace.py"


def _job(*, manifest, question="Vad gäller uppsägning?", result=None, created_at=STAMP):
    job = Job(
        id="job-chat-1",
        customer_id=1,
        kind="workspace_research",
        status="completed",
        label=question[:120],
        created_at=created_at,
        request={
            "chat_id": "chat-1",
            "workspace_id": "ws-1",
            "question": question,
            "document_manifest": manifest,
        },
        result=result,
    )
    return job


def _result(*, version="ver-1", extra=()):
    return {
        "attempt_id": "attempt-1",
        "answer": "Svar om uppsägning.",
        "citations": [
            {
                "label": "E1",
                "document_version_id": version,
                "text_unit_id": "unit-1",
                "excerpt": "Paragraf 12",
            },
            *extra,
        ],
    }


def _one_doc():
    return [{
        "source_object_id": "obj-1",
        "document_id": "doc-1",
        "document_version_id": "ver-1",
        "workspace_id": "ws-1",
    }]


async def _seed(session):
    session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
    await session.flush()
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


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/qa-chat.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


def test_producer_never_opens_overgraph_or_reuses_answers():
    text = SOURCE.read_text()
    assert "TenantCatalogs" not in text
    assert "open_catalog" not in text
    assert "exact_reuse" not in text
    assert "semantic_candidates" not in text


def test_one_document_answer_keeps_version_question_and_cites():
    seed = workspace_qa_seed(_job(manifest=_one_doc()), _result())
    write = qa_write_from_seed(seed)
    assert write is not None
    assert write.document_id == "doc-1"
    assert write.document_version_id == "ver-1"
    assert write.question_text == "Vad gäller uppsägning?"
    assert write.answer_text == "Svar om uppsägning."
    assert write.status == "ANSWERED"
    assert write.embedding is None
    assert write.contract.kind == "document_chat"
    assert write.contract.method == "workspace_research"
    assert write.contract.examined_scope == "retrieved_evidence"
    assert write.contract.question_context == ""
    assert write.contract.model == settings.selected_llm_model
    assert len(write.posts[0].sources) == 1
    cite = write.posts[0].sources[0]
    assert cite.text_unit_id == "unit-1"
    assert cite.excerpt == "Paragraf 12"


def test_foreign_version_and_external_cites_are_dropped():
    seed = workspace_qa_seed(_job(manifest=_one_doc()), _result(extra=(
        {"document_version_id": "ver-2", "text_unit_id": "unit-x", "excerpt": "Annat"},
        {"document_version_id": "ver-1", "text_unit_id": None, "excerpt": "Lagen.nu"},
    )))
    write = qa_write_from_seed(seed)
    assert write is not None
    assert [cite.text_unit_id for cite in write.posts[0].sources] == ["unit-1"]


def test_multi_document_and_empty_manifest_are_not_persisted():
    two = _one_doc() + [{
        "source_object_id": "obj-2",
        "document_id": "doc-2",
        "document_version_id": "ver-2",
        "workspace_id": "ws-1",
    }]
    assert workspace_qa_seed(_job(manifest=two), _result()) is None
    assert workspace_qa_seed(_job(manifest=[]), _result()) is None
    assert qa_write_from_seed(workspace_qa_seed(
        _job(manifest=_one_doc()),
        {"answer": "Svar.", "citations": []},
    )) is None


@pytest.mark.asyncio
async def test_finished_answer_enqueues_document_qa_write(factory):
    async with factory() as session:
        await _seed(session)
        job = _job(manifest=_one_doc(), result=_result())
        session.add(job)
        await session.flush()
        work_id = await enqueue_workspace_document_answer(
            session, workspace_qa_seed(job, job.result),
        )
    assert work_id is not None
    async with factory() as session:
        row = await session.get(GraphIngestWork, work_id)
        assert row.status == "pending"
        assert row.customer_id == 1
        assert row.payload["kind"] == DOCUMENT_QA_WRITE
        assert "customer_id" not in row.payload
        assert row.payload["document_id"] == "doc-1"
        assert row.payload["document_version_id"] == "ver-1"
        assert row.payload["question_text"] == "Vad gäller uppsägning?"
        assert row.payload["answer_text"] == "Svar om uppsägning."
        assert row.payload["posts"][0]["sources"][0]["text_unit_id"] == "unit-1"
        assert row.payload["posts"][0]["sources"][0]["excerpt"] == "Paragraf 12"
        assert row.payload["embedding"] is None
        assert await session.scalar(select(func.count()).select_from(GraphIngestWork)) == 1


@pytest.mark.asyncio
async def test_writeback_failure_does_not_raise(factory, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise PermanentGraphError("document version is missing")

    monkeypatch.setattr(
        "app.services.document_qa.from_workspace.enqueue_document_qa", boom,
    )
    async with factory() as session:
        job = _job(manifest=_one_doc(), result=_result())
        session.add(job)
        await session.commit()
        seed = workspace_qa_seed(job, job.result)
        assert await enqueue_workspace_document_answer(session, seed) is None
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(GraphIngestWork)) == 0
