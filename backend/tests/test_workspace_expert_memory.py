"""Client research cannot reach the existing tenant-wide expert memory seam."""

from unittest.mock import Mock

import pytest

from app.database.models import ExecutionRun
from app.services.research.expert_knowledge import (
    ExpertKnowledgeMemory,
    publish_completed_attempt_knowledge,
    publish_research_question_knowledge,
    remember_published_question,
)
from app.services.research.question_graph_memory import InMemoryQuestionEvidenceGraph
from tests.test_research_question_attempt_worker import _setup


async def test_workspace_dag_publication_fails_before_graph_or_memory(client_db):
    _client, factory = client_db
    attempt_id, question_id = await _setup(factory)
    async with factory.begin() as session:
        from app.database.models import ExecutionAttempt

        attempt = await session.get(ExecutionAttempt, attempt_id)
        run = await session.get(ExecutionRun, attempt.run_id)
        run.context = {**run.context, "workspace_id": "private-client"}
    graph = InMemoryQuestionEvidenceGraph()
    async with factory() as session:
        with pytest.raises(ValueError, match="tenant-wide expert memory"):
            await publish_research_question_knowledge(
                session, research_question_id=question_id, graph=graph
            )
        with pytest.raises(ValueError, match="tenant-wide expert memory"):
            await publish_completed_attempt_knowledge(session, attempt_id=attempt_id, graph=graph)
    assert graph.links() == []


async def test_workspace_receipt_rejected_before_memory_initialization(monkeypatch):
    initialize = Mock(side_effect=AssertionError("Memory must not be initialized"))
    monkeypatch.setattr("app.services.research.expert_knowledge.get_expert_memory", initialize)
    receipt = ExpertKnowledgeMemory(
        customer_id=1,
        persona_id="expert",
        memory_expert_id="expert",
        question="Private contract?",
        knowledge_question_id="question",
        source_attempt_id="attempt",
        workspace_id="private-client",
    )
    with pytest.raises(ValueError, match="tenant-wide expert memory"):
        await remember_published_question([receipt])
    initialize.assert_not_called()
