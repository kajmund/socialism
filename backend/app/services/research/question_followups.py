"""Resolve canonical children once per attempt, preserving decomposition lineage."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchContext
from app.services.research.knowledge_question import tenant_question_scope
from app.services.research.question_graph import QuestionEvidenceGraph
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.research.question_iteration import QuestionRelationResolver


async def prepare_iterative_follow_ups(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    context: ResearchContext,
    accepted: Sequence[RuntimeResearchNeed],
    previous: Sequence[RuntimeResearchNeed],
    relations: QuestionRelationResolver | None = None,
) -> list[RuntimeResearchNeed]:
    """Resolve child identities; retrieval and assessment happen during execution."""
    from app.services.research.question_iteration import (
        resolve_or_create_knowledge_question,
        lineage_ancestors,
        record_question_lineage,
        _parent_question_id,
    )

    customer_id = context.scope.customer_id
    if customer_id is None:
        return list(accepted)
    scope = tenant_question_scope(customer_id)
    from app.services.research.question_prepare import prepare_graph_questions
    from app.services.research.execution import _session_factory

    from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph

    if (
        isinstance(graph, SqlQuestionEvidenceGraph)
        and graph._matcher.embedding_metadata is not None
    ):
        await prepare_graph_questions(
            _session_factory(session), graph, context, [row.question for row in accepted]
        )
    seen = {row.knowledge_question_id for row in previous if row.knowledge_question_id}
    previous_by_id = {row.research_need_id: row for row in previous}
    prepared: list[RuntimeResearchNeed] = []
    max_depth = settings.research_max_follow_up_waves
    for need in accepted:
        child = await resolve_or_create_knowledge_question(
            session,
            graph=graph,
            question=need.question,
            scope=scope,
            relations=relations,
        )
        parent_id = _parent_question_id(need, previous_by_id)
        if parent_id is None and need.parent_research_need_id:
            parent_need = previous_by_id.get(need.parent_research_need_id)
            if parent_need is not None:
                parent = await resolve_or_create_knowledge_question(
                    session,
                    graph=graph,
                    question=parent_need.question,
                    scope=scope,
                    relations=relations,
                )
                parent_id = parent.id
        if parent_id is not None:
            ancestors = await lineage_ancestors(session, parent_id)
            if child.id in ancestors or len(ancestors) > max_depth:
                continue
            await record_question_lineage(
                session,
                parent_question_id=parent_id,
                child_question_id=child.id,
                why_needed=need.why_needed or need.source_gap,
                trigger_claim_id=need.trigger_claim_id or None,
                trigger_graph_event_id=need.trigger_graph_event_id or None,
            )
        if child.id in seen:
            continue
        seen.add(child.id)
        prepared.append(
            replace(
                need,
                knowledge_question_id=child.id,
                generated_from_question_id=parent_id or "",
                question_key=child.identity_key,
            )
        )
    return prepared
