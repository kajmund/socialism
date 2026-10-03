"""Question→fact dependencies used for Graph reuse, not revalidation queues."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import (
    GraphFact,
    GraphFactQuestionDependency,
    GraphFactSource,
    GraphNode,
)
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.identity import stable_id


async def attach_question_dependency(
    session: AsyncSession, *, question_node_id: str, fact_id: str,
) -> GraphFactQuestionDependency:
    """Link an answer fact to its canonical question and snapshot exact provenance."""
    question = await session.get(GraphNode, question_node_id)
    fact = await session.get(GraphFact, fact_id)
    if question is None or question.node_type != "core.question" or fact is None:
        raise PermanentGraphError("question dependency requires a persisted question node and fact")
    if question.scope_key != fact.scope_key and fact.scope_key != "shared":
        raise PermanentGraphError("question dependency cannot cross tenant scopes")
    sources = await fact_provenance(session, fact_id)
    if not sources:
        raise PermanentGraphError("question dependency requires fact provenance")
    dependency_id = stable_id("question-depends-on", question_node_id, fact_id)
    row = await session.get(GraphFactQuestionDependency, dependency_id)
    if row is not None:
        row.provenance = sources
        await session.flush()
        return row
    row = GraphFactQuestionDependency(
        id=dependency_id, scope_key=question.scope_key, question_node_id=question_node_id,
        fact_id=fact_id, relation="research.depends_on", provenance=sources,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        row = await session.scalar(select(GraphFactQuestionDependency).where(
            GraphFactQuestionDependency.question_node_id == question_node_id,
            GraphFactQuestionDependency.fact_id == fact_id,
        ))
        if row is None:
            raise
    return row


async def fact_provenance(session: AsyncSession, fact_id: str) -> list[dict[str, str]]:
    rows = (await session.execute(
        select(GraphFactSource.source_kind, GraphFactSource.source_ref)
        .where(GraphFactSource.fact_id == fact_id)
        .order_by(GraphFactSource.source_kind, GraphFactSource.source_ref)
    )).all()
    return [{"kind": kind, "ref": ref} for kind, ref in rows]
