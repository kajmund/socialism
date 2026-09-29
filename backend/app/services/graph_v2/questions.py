"""Project canonical questions and decomposition into Graph v2."""

from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.database.models import KnowledgeQuestionLineage, KnowledgeQuestionRow
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.scope import require_persist_scope


async def question_node(session: AsyncSession, question: KnowledgeQuestionRow):
    scope = require_persist_scope(
        scope_type=question.scope_type, customer_id=question.customer_id,
    )
    return await resolve_node(session, NodeInput(
        node_type="core.question", name=question.display_text, scope=scope,
        identifier_namespace="research.question_id", identifier=question.id,
        attributes={"canonical_question_id": question.id},
    ))


async def link_decomposition(
    session: AsyncSession, parent: KnowledgeQuestionRow, child: KnowledgeQuestionRow,
) -> None:
    source = await question_node(session, parent)
    target = await question_node(session, child)
    scope = require_persist_scope(
        scope_type=parent.scope_type, customer_id=parent.customer_id,
    )
    if child.scope_key != parent.scope_key:
        raise ValueError("decomposition cannot cross question scopes")
    await resolve_fact(session, FactInput(
        source_id=source.id, target_id=target.id, scope=scope,
        predicate="research.decomposed_to",
        fact_text=f"{parent.display_text} → {child.display_text}",
        sources=(SourceRef("episode", parent.id),),
    ))


async def persist_decomposition(
    session: AsyncSession, *, parent_id: str, child_id: str,
    why_needed: str, trigger_claim_id: str | None, trigger_graph_event_id: str | None,
) -> None:
    session.add(KnowledgeQuestionLineage(
        id=uuid4().hex, parent_question_id=parent_id, child_question_id=child_id,
        trigger_claim_id=trigger_claim_id, trigger_graph_event_id=trigger_graph_event_id,
        why_needed=why_needed,
    ))
    await session.flush()
    parent = await session.get(KnowledgeQuestionRow, parent_id)
    child = await session.get(KnowledgeQuestionRow, child_id)
    await link_decomposition(session, parent, child)
