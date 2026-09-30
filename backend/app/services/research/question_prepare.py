"""Canonical identity matching with database and remote vector phases separated."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import KnowledgeQuestionRow
from app.services.graph_v2.questions import question_node
from app.services.knowledge.scope import persist_scope_fields
from app.services.research.knowledge_question import (
    KnowledgeQuestion,
    KnowledgeQuestionScope,
    identity_from_text,
    public_question_scope,
    tenant_question_scope,
)
from app.services.research.models import ResearchContext, ResearchNeed, ResearchEvidence
from app.services.research.question_graph import QuestionEvidenceGraph

if TYPE_CHECKING:
    from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
    from app.services.research.question_execution import QuestionResearchOutcome


async def prepare_sql_question(
    factory: async_sessionmaker[AsyncSession],
    graph: SqlQuestionEvidenceGraph,
    text: str,
    scope: KnowledgeQuestionScope,
) -> KnowledgeQuestion:
    from app.services.research.question_graph_sql import _question_from_row

    identity = identity_from_text(text)
    async with factory() as session:
        rows = list(
            await session.scalars(
                select(KnowledgeQuestionRow).where(
                    KnowledgeQuestionRow.namespace == scope.namespace,
                )
            )
        )
        candidates = [_question_from_row(row) for row in rows]
    matched = next((row for row in candidates if row.identity_key == identity.identity_key), None)
    await graph._matcher.index(candidates)
    await _indexed_metadata(factory, candidates, graph._matcher.embedding_metadata)
    if matched is None:
        matched = await graph._matcher.match(
            normalized_text=identity.normalized_text,
            identity_key=identity.identity_key,
            candidates=candidates,
        )
    if matched is not None:
        if matched.scope != scope:
            raise ValueError("Semantic question matching crossed a tenant boundary")
        return matched
    async with factory.begin() as session:
        row = KnowledgeQuestionRow(
            id=uuid4().hex,
            identity_key=identity.identity_key,
            normalized_text=identity.normalized_text,
            display_text=identity.display_text,
            namespace=scope.namespace,
            visibility=scope.visibility,
            embedding_model=None,
            embedding_version=None,
            embedding_dimension=None,
            **persist_scope_fields(scope.tenant),
        )
        session.add(row)
        await session.flush()
        await question_node(session, row)
        created = _question_from_row(row)
    await graph._matcher.index([created])
    await _indexed_metadata(factory, [created], graph._matcher.embedding_metadata)
    return created


async def prepare_graph_questions(
    factory: async_sessionmaker[AsyncSession],
    graph: QuestionEvidenceGraph,
    context: ResearchContext,
    questions: Sequence[str],
) -> None:
    from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph

    if not isinstance(graph, SqlQuestionEvidenceGraph):
        return
    if context.scope.customer_id is None:
        raise ValueError("Canonical question preparation requires customer_id")
    scope = tenant_question_scope(context.scope.customer_id)
    for text in dict.fromkeys(questions):
        question = await prepare_sql_question(factory, graph, text, scope)
        graph.prepared[(scope.namespace, identity_from_text(text).identity_key)] = question


async def _indexed_metadata(factory, candidates, metadata) -> None:
    if metadata is None or not candidates:
        return
    async with factory.begin() as session:
        for question in candidates:
            row = await session.get(KnowledgeQuestionRow, question.id)
            row.embedding_model, row.embedding_version, row.embedding_dimension = metadata


async def prepare_domain_graph(
    factory: async_sessionmaker[AsyncSession],
    customer_id: int,
    questions: Sequence[str],
) -> SqlQuestionEvidenceGraph:
    from app.services.research.composition import build_standard_question_graph
    from app.services.knowledge.models import KnowledgeScope

    graph = build_standard_question_graph()
    await prepare_graph_questions(
        factory, graph, ResearchContext(scope=KnowledgeScope(customer_id=customer_id)), questions
    )
    return graph


async def prepare_outcome_graph(
    factory: async_sessionmaker[AsyncSession],
    attempt_id: str,
    outcomes: Sequence[QuestionResearchOutcome | BaseException],
) -> SqlQuestionEvidenceGraph:
    from app.services.execution.service import get_attempt, get_run

    async with factory() as session:
        run = await get_run(session, (await get_attempt(session, attempt_id)).run_id)
        customer_id = run.customer_id
    questions = [
        child.question
        for outcome in outcomes
        if not isinstance(outcome, BaseException)
        for child in outcome.follow_ups
    ]
    return await prepare_domain_graph(factory, customer_id, questions)


@dataclass(frozen=True)
class QuestionInventory:
    customer_id: int
    needs: tuple[ResearchNeed, ...]
    graph: QuestionEvidenceGraph


async def prepare_question_inventory(
    factory: async_sessionmaker[AsyncSession],
    customer_id: int,
    needs: Sequence[ResearchNeed],
) -> QuestionInventory:
    graph = await prepare_domain_graph(factory, customer_id, [need.question for need in needs])
    return QuestionInventory(customer_id, tuple(needs), graph)


async def prepare_public_writeback(
    factory: async_sessionmaker[AsyncSession],
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    evidence: Sequence[ResearchEvidence],
) -> None:
    from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
    from app.services.research.knowledge_question import evidence_visibility

    if not isinstance(graph, SqlQuestionEvidenceGraph):
        return
    if not any(
        item.status == "found"
        and evidence_visibility(item.metadata) == "public"
        and item.metadata.get("reuse", {}).get("origin") != "persistent_knowledge"
        for item in evidence
    ):
        return
    scope = public_question_scope()
    question = await prepare_sql_question(factory, graph, need.question, scope)
    graph.prepared[(scope.namespace, identity_from_text(need.question).identity_key)] = question
