"""Project canonical questions and decomposition into Graph v2."""

from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.database.models import KnowledgeQuestionLineage, KnowledgeQuestionRow
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import require_persist_scope


async def link_decomposition(
    session: AsyncSession, parent: KnowledgeQuestionRow, child: KnowledgeQuestionRow,
) -> None:
    """Parent → child decomposition, written as one owner mutation."""
    from app.services.overgraph.answers import QUESTION_NS, QUESTION_TYPE
    from app.services.overgraph.owner_facts import write_fact_via_owner
    from app.services.overgraph.owner_runtime import get_owner_runtime
    from app.services.overgraph.write import entity_key, fact_key_from_anchor

    if parent is None or child is None:
        raise PermanentGraphError("decomposition needs both questions")
    if child.scope_key != parent.scope_key:
        raise PermanentGraphError("decomposition cannot cross question scopes")
    scope = require_persist_scope(
        scope_type=parent.scope_type, customer_id=parent.customer_id,
    )
    parent_input = NodeInput(
        node_type=QUESTION_TYPE,
        name=parent.display_text,
        scope=scope,
        identifier_namespace=QUESTION_NS,
        identifier=parent.id,
        attributes={"canonical_question_id": parent.id},
    )
    child_input = NodeInput(
        node_type=QUESTION_TYPE,
        name=child.display_text,
        scope=scope,
        identifier_namespace=QUESTION_NS,
        identifier=child.id,
        attributes={"canonical_question_id": child.id},
    )
    proposed = FactInput(
        source_id=entity_key(parent_input),
        target_id=entity_key(child_input),
        scope=scope,
        predicate="research.decomposed_to",
        fact_text=f"{parent.display_text} → {child.display_text}",
        sources=(SourceRef("episode", parent.id),),
        occurrence_key=child.id,
    )
    fact_id = fact_key_from_anchor(proposed, None)
    await write_fact_via_owner(
        get_owner_runtime().require_client(),
        proposed,
        entities=(parent_input, child_input),
        dependency_ids=(fact_id,),
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
