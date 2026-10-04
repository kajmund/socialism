"""Canonical private research questions stay inside their workspace."""

import pytest
from sqlalchemy import select

from app.database.models import KnowledgeQuestionRow
from app.database.workspace_ids import company_workspace_id
from app.services.knowledge.models import KnowledgeScope
from app.services.research.expert_knowledge import _canonical_question
from app.services.research.knowledge_question import (
    KnowledgeQuestionError,
    KnowledgeQuestionScope,
    identity_from_text,
    lookup_scopes,
    question_scope_from_namespace,
    tenant_question_scope,
)
from app.services.research.models import ResearchContext, ResearchNeed, research_evidence
from app.services.research.question_graph_memory import InMemoryQuestionEvidenceGraph
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.question_iteration import question_from_row
from app.services.research.question_prepare import prepare_graph_questions, prepare_public_writeback
from app.services.research.question_reuse import upsert_persisted_evidence


def test_private_scope_defaults_to_company_and_lookup_never_includes_sibling():
    common = tenant_question_scope(1)
    assert common.workspace_id == company_workspace_id(1)
    assert common == KnowledgeQuestionScope(visibility="tenant", customer_id=1)
    assert common.namespace == f"tenant:1:workspace:{company_workspace_id(1)}"
    scopes = lookup_scopes(1, "client-a")
    assert [scope.workspace_id for scope in scopes] == ["client-a", company_workspace_id(1), None]
    assert scopes[-1].namespace == "public"
    assert (
        question_scope_from_namespace(scopes[0].namespace, visibility="tenant", customer_id=1)
        == scopes[0]
    )


@pytest.mark.parametrize(
    "namespace,visibility,customer",
    [
        ("tenant:2:workspace:client-a", "tenant", 1),
        ("tenant:1:workspace:", "tenant", 1),
        ("public", "public", 1),
    ],
)
def test_invalid_persisted_namespace_is_rejected(namespace, visibility, customer):
    with pytest.raises(KnowledgeQuestionError):
        question_scope_from_namespace(namespace, visibility=visibility, customer_id=customer)


async def test_sql_question_identity_is_separate_for_each_workspace(client_db):
    _client, factory = client_db
    graph = SqlQuestionEvidenceGraph()
    question = "När får avtalet sägas upp?"
    contexts = [
        ResearchContext(scope=KnowledgeScope(customer_id=1, workspace_id=value))
        for value in (None, "client-a", "client-b")
    ]
    for context in contexts:
        await prepare_graph_questions(factory, graph, context, [question])
    async with factory() as session:
        ids = []
        for context in contexts:
            found = await graph.match_question(
                session,
                identity_from_text(question),
                tenant_question_scope(1, context.scope.workspace_id),
            )
            ids.append(found.id)
            assert found.scope.workspace_id == (
                context.scope.workspace_id or company_workspace_id(1)
            )
            persisted = await session.get(KnowledgeQuestionRow, found.id)
            assert question_from_row(persisted).scope == found.scope
            assert _canonical_question(persisted).scope == found.scope
        assert len(set(ids)) == 3
        assert len(list(await session.scalars(select(KnowledgeQuestionRow)))) == 3


@pytest.mark.parametrize("workspace_id", [None, "client-a"])
async def test_workspace_research_does_not_publish_private_question_even_with_public_source(
    client_db,
    workspace_id,
):
    _client, factory = client_db
    graph = InMemoryQuestionEvidenceGraph()
    context = ResearchContext(scope=KnowledgeScope(customer_id=1, workspace_id=workspace_id))
    need = ResearchNeed(
        id="need",
        question="Hur berör lagen klientens hemliga avtal?",
        why_needed="Avtalsbedömning",
        source_types=["swedish_law"],
    )
    evidence = research_evidence(
        research_need_id="need",
        source_type="swedish_law",
        status="found",
        excerpt="Public legal text",
        source_id="law",
        provider="lagen_nu",
        metadata={"public": True},
    )
    async with factory() as session:
        await upsert_persisted_evidence(
            session, graph=graph, need=need, context=context, evidence=[evidence]
        )
    assert len(graph.questions()) == 1
    assert graph.questions()[0].scope == tenant_question_scope(1, workspace_id)
    assert len(graph.links()) == 1
    sql_graph = SqlQuestionEvidenceGraph()
    await prepare_public_writeback(factory, sql_graph, need, [evidence], context=context)
    assert sql_graph.prepared == {}
