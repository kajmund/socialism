"""An insufficient Graph answer uses cached source text and its stored vectors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
from app.services.research.graph_lookup import lookup_question
from app.services.research.models import ResearchNeed
from app.services.research.need_retrieval import candidates_then_providers, NeedReusePolicy
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.reuse_gate import assess_reuse, answer_is_sufficient
from tests.research_reuse.cached_source_helpers import (
    QUESTION, available_connection, seed_cache, source_boundary,
)
from tests.research_reuse.helpers import context, reviewed_answer

pytestmark = pytest.mark.research_reuse


@pytest.fixture
async def cached_source(reuse_db):
    return await seed_cache(reuse_db)


async def _retrieve(cache, boundary, need):
    reused = await lookup_question(cache.factory, need, context(), boundary.embedding)
    assert reused and all(item.provider == "graph_v2" for item in reused)

    async def insufficient(plan, items):
        assert [row.id for row in plan.needs] == [need.id]
        assert items and all(item.provider == "graph_v2" for item in items)
        await available_connection(cache.factory)
        return ResearchAssessmentDraft(
            result="insufficient", rationale="The mock judgment requests source detail",
            need_assessments=[ResearchNeedAssessment(
                research_need_id=need.id, sufficient=False, missing_or_weak="Conditions for adjustment",
            )],
        )

    assessor = SimpleNamespace(assess=AsyncMock(side_effect=insufficient))
    items = await candidates_then_providers(
        factory=cache.factory, need=need, context=context(), router=None,
        router_factory=boundary.router_factory, reused=reused,
        policy=NeedReusePolicy(assessor, SqlQuestionEvidenceGraph()),
    )
    assessor.assess.assert_awaited_once()
    return items


@pytest.mark.parametrize("need_id", ["research-main", "child"])
async def test_insufficient_knowledge_uses_cached_source_without_reprocessing(
    cached_source, monkeypatch, need_id,
):
    before = await cached_source.snapshot()
    boundary = source_boundary(cached_source, monkeypatch)
    get_vectors = cached_source.store.get_text_unit_embeddings

    async def cached_vectors(**kwargs):
        await available_connection(cached_source.factory)
        return await get_vectors(**kwargs)

    cached_source.store.get_text_unit_embeddings = AsyncMock(side_effect=cached_vectors)
    need = ResearchNeed(id=need_id, question=QUESTION, why_needed="Gap", source_types=["swedish_law"])
    items = await _retrieve(cached_source, boundary, need)
    found = [item for item in items if item.provider == "lagen_nu"]
    assert len(found) == 1 and found[0].status == "found"
    metadata = found[0].metadata
    assert metadata["reused_text_units"] is True
    assert metadata["canonical_document_id"] == cached_source.document_id
    assert metadata["document_version_id"] == cached_source.version_id
    assert set(metadata["text_unit_ids"]) == set(cached_source.unit_ids)
    cached_source.store.get_text_unit_embeddings.assert_awaited_once_with(
        document_id=cached_source.document_id, document_version_id=cached_source.version_id,
        text_unit_ids=cached_source.unit_ids,
    )
    assert len(boundary.jev.asks) == 1
    boundary.interpreter.interpret.assert_awaited_once()
    assessment = await assess_reuse(
        SimpleNamespace(assess=AsyncMock(side_effect=reviewed_answer)), need, items,
    )
    assert answer_is_sufficient(assessment)
    assert await cached_source.snapshot() == before
    assert boundary.embedding.calls == [(QUESTION,), (QUESTION,)]
    boundary.client.get_document.assert_not_awaited()
    boundary.ingest.assert_not_awaited()
    boundary.chunk.assert_not_called()
    cached_source.store.replace_document_chunks.assert_not_awaited()


async def test_missing_cached_vectors_report_error_without_refetch_or_reembedding(
    cached_source, monkeypatch,
):
    from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore

    cached_source.store = MemoryKnowledgeVectorStore()
    boundary = source_boundary(cached_source, monkeypatch)
    need = ResearchNeed(id="child", question=QUESTION, why_needed="Gap", source_types=["swedish_law"])
    items = await _retrieve(cached_source, boundary, need)
    found = [item for item in items if item.provider == "lagen_nu"]
    assert len(found) == 1 and found[0].status == "error"
    boundary.client.get_document.assert_not_awaited()
    boundary.interpreter.interpret.assert_not_awaited()
    boundary.ingest.assert_not_awaited()
    boundary.chunk.assert_not_called()
    assert boundary.embedding.calls == [(QUESTION,), (QUESTION,)]
