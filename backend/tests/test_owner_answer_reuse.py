"""Owner-backed research answer reuse.

Publication goes through the production owner fact writer; lookup must use the
owner read path, not a backend-local catalog snapshot.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.services.knowledge.models import KnowledgeScope
from app.services.overgraph.owner_facts import answer_fact_key, publish_answer_via_owner
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.publish import AnswerPublish
from app.services.research.answer_graph import lookup_answers
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed

BASIS = TypeAdapter(list[ResearchEvidence])


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()


def _evidence(now: datetime) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id="evidence-reuse-1",
        research_need_id="need-reuse-1",
        source_type="document",
        status="found",
        title="Uppsägningstid",
        excerpt="Nio månader",
        locator="sida 1",
        source_id="doc-reuse",
        source_url=None,
        provider="uploaded_file",
        score=1.0,
        retrieved_at=now,
        metadata={"reuse": {"evidence_ref": "doc-reuse:1"}},
    )


async def test_backend_finds_answer_published_through_owner(session, monkeypatch):
    from app.services.knowledge.scope import customer_scope

    now = datetime.now(UTC)
    basis = [json.loads(BASIS.dump_json([_evidence(now)]))[0]]
    published = AnswerPublish(
        question_id="question-reuse-1",
        question_text="Vad gäller uppsägningstiden?",
        scope=customer_scope(1),
        identity="answer-reuse-identity",
        evidence_set_id="evidence-set-reuse",
        attributes={
            "knowledge_module": "dd",
            "knowledge_case_id": None,
            "workspace_id": None,
            "document_version_ids": [],
            "answer_status": "sufficient",
        },
        basis=basis,
        assessment={"sufficient": True},
        dependency_ids=(),
    )
    client = get_owner_runtime().require_client()
    published_id = await publish_answer_via_owner(client, published)

    need = ResearchNeed(
        id="need-reuse-1",
        question="Vad gäller uppsägningstiden?",
        why_needed="answers a repeated legal question",
        source_types=["document"],
        knowledge_question_id="question-reuse-1",
    )
    context = ResearchContext(
        scope=KnowledgeScope(customer_id=1, module="dd"), limit=10,
    )
    found = await lookup_answers(
        session, need=need, context=context, now=now + timedelta(seconds=1),
    )
    assert len(found) == 1
    assert found[0].source_id == "doc-reuse"
    assert found[0].provider == "graph_v2"
    assert found[0].metadata["answer_fact_id"] == answer_fact_key(published)
    assert found[0].metadata["answer_fact_id"] == published_id
    assert found[0].metadata["reuse"]["evidence_ref"] == "doc-reuse:1"
