"""Project canonical questions and decomposition into Graph v2."""

from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.database.models import KnowledgeQuestionLineage, KnowledgeQuestionRow
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import require_persist_scope


async def link_decomposition(
    session: AsyncSession, parent: KnowledgeQuestionRow, child: KnowledgeQuestionRow,
) -> None:
    """Parent → child decomposition edge in OverGraph (SQL graph_v2 is retired)."""
    from app.services.overgraph.catalogs import require_knowledge
    from app.services.overgraph.questions import upsert_question_entity
    from app.services.overgraph.research import attach_question_dependency
    from app.services.overgraph.write import write_fact

    if parent is None or child is None:
        raise PermanentGraphError("decomposition needs both questions")
    if child.scope_key != parent.scope_key:
        raise PermanentGraphError("decomposition cannot cross question scopes")
    scope = require_persist_scope(
        scope_type=parent.scope_type, customer_id=parent.customer_id,
    )
    catalog = require_knowledge()
    parent_node = upsert_question_entity(
        question_id=parent.id, display_text=parent.display_text, scope=scope,
    )
    child_node = upsert_question_entity(
        question_id=child.id, display_text=child.display_text, scope=scope,
    )
    fact = write_fact(catalog, FactInput(
        source_id=parent_node.key, target_id=child_node.key, scope=scope,
        predicate="research.decomposed_to",
        fact_text=f"{parent.display_text} → {child.display_text}",
        sources=(SourceRef("episode", parent.id),),
        occurrence_key=child.id,
    ))
    attach_question_dependency(
        catalog,
        question_id=parent.id,
        question_text=parent.display_text,
        fact_id=str(fact.key),
        scope=scope,
    )


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
