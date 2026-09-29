"""Fact-edge revalidation candidates scoped through Graph v2 provenance and questions."""

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import (
    GraphFact,
    GraphFactQuestionDependency,
    GraphFactRevalidation,
    GraphFactSource,
    GraphNode,
    GraphQuestionRevalidationWork,
)
from app.services.graph_v2.identity import stable_id


async def attach_question_dependency(
    session: AsyncSession, *, question_node_id: str, fact_id: str,
) -> GraphFactQuestionDependency:
    """Link an answer fact to its canonical question and snapshot exact provenance."""
    question = await session.get(GraphNode, question_node_id)
    fact = await session.get(GraphFact, fact_id)
    if question is None or question.node_type != "core.question" or fact is None:
        raise ValueError("question dependency requires a persisted question node and fact")
    if question.scope_key != fact.scope_key and question.scope_key != "shared":
        raise ValueError("question dependency cannot cross tenant scopes")
    sources = await fact_provenance(session, fact_id)
    if not sources:
        raise ValueError("question dependency requires fact provenance")
    dependency_id = stable_id("question-depends-on", question_node_id, fact_id)
    row = await session.get(GraphFactQuestionDependency, dependency_id)
    if row is not None:
        return row
    row = GraphFactQuestionDependency(
        id=dependency_id, scope_key=fact.scope_key, question_node_id=question_node_id,
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


async def schedule_fact_revalidation(
    session: AsyncSession, *, trigger_fact_id: str, question_node_id: str | None = None,
) -> int:
    """Queue structurally related changes for each dependent question.

    This only creates candidates. It never invalidates facts or lets semantic
    similarity alone alter existing knowledge.
    """
    trigger = await session.get(GraphFact, trigger_fact_id)
    if trigger is None:
        raise ValueError("revalidation trigger fact is missing")
    trigger_sources = await fact_provenance(session, trigger.id)
    if not trigger_sources:
        return 0
    candidates = (await session.execute(
        select(GraphFactQuestionDependency, GraphFact)
        .join(GraphFact, GraphFact.id == GraphFactQuestionDependency.fact_id)
        .where(
            GraphFactQuestionDependency.scope_key == trigger.scope_key,
            *([GraphFactQuestionDependency.question_node_id == question_node_id]
              if question_node_id is not None else []),
            GraphFact.scope_key == trigger.scope_key,
            GraphFact.id != trigger.id,
            GraphFact.status == "active",
            or_(
                GraphFact.created_at < trigger.created_at,
                and_(GraphFact.created_at == trigger.created_at, GraphFact.id < trigger.id),
            ),
            GraphFact.predicate == trigger.predicate,
            GraphFact.context_id == trigger.context_id,
            GraphFact.occurrence_key == trigger.occurrence_key,
            or_(
                GraphFact.source_id == trigger.source_id,
                GraphFact.target_id == trigger.target_id,
            ),
        )
    )).all()
    queued = 0
    for dependency, dependent in candidates:
        dependent_sources = await fact_provenance(session, dependent.id)
        row_id = stable_id(
            "graph-fact-revalidation", trigger.id, dependent.id, dependency.question_node_id,
        )
        if await session.get(GraphFactRevalidation, row_id) is not None:
            continue
        row = GraphFactRevalidation(
            id=row_id, scope_key=trigger.scope_key, trigger_fact_id=trigger.id,
            dependent_fact_id=dependent.id, question_node_id=dependency.question_node_id,
            trigger_provenance=trigger_sources, dependent_provenance=dependent_sources,
            status="pending", attempts=0,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
            queued += 1
        except IntegrityError:
            if await session.get(GraphFactRevalidation, row_id) is None:
                raise
    return queued


async def enqueue_question_revalidation(
    session: AsyncSession, *, customer_id: int, question_node_id: str,
    evidence_set_id: str,
) -> GraphQuestionRevalidationWork:
    """Record a complete answer-basis review request at the shared freeze boundary."""
    question = await session.get(GraphNode, question_node_id)
    if question is None or question.node_type != "core.question":
        raise ValueError("revalidation work requires a canonical question node")
    scope_key = f"customer:{customer_id}"
    if question.scope_key not in {scope_key, "shared"}:
        raise ValueError("question revalidation cannot cross tenant scope")
    work_id = stable_id("graph-question-revalidation", scope_key, question_node_id, evidence_set_id)
    row = await session.get(GraphQuestionRevalidationWork, work_id)
    if row is not None:
        return row
    row = GraphQuestionRevalidationWork(
        id=work_id, scope_key=scope_key, question_node_id=question_node_id,
        evidence_set_id=evidence_set_id, status="pending", attempts=0,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        row = await session.get(GraphQuestionRevalidationWork, work_id)
        if row is None:
            raise
    return row


async def process_question_revalidation_work(
    session: AsyncSession, *, limit: int = 50,
) -> dict[str, int]:
    """Materialize question reviews only after the complete basis has frozen."""
    from datetime import UTC, datetime

    completed = waiting = 0
    work_items = list((await session.scalars(
        select(GraphQuestionRevalidationWork)
        .where(GraphQuestionRevalidationWork.status == "pending")
        .order_by(GraphQuestionRevalidationWork.created_at, GraphQuestionRevalidationWork.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )).all())
    for work in work_items:
        work.status = "processing"
        work.attempts += 1
        fact_ids = list((await session.scalars(
            select(GraphFactQuestionDependency.fact_id).where(
                GraphFactQuestionDependency.scope_key == work.scope_key,
                GraphFactQuestionDependency.question_node_id == work.question_node_id,
            ).order_by(GraphFactQuestionDependency.fact_id)
        )).all())
        if not fact_ids:
            # Graph projection may still be in the outbox; keep the request durable.
            work.status = "pending"
            waiting += 1
            continue
        for fact_id in fact_ids:
            await schedule_fact_revalidation(
                session, trigger_fact_id=fact_id, question_node_id=work.question_node_id,
            )
        work.status = "completed"
        work.processed_at = datetime.now(UTC)
        completed += 1
    await session.flush()
    return {"completed": completed, "waiting": waiting}


async def fact_provenance(session: AsyncSession, fact_id: str) -> list[dict[str, str]]:
    rows = (await session.execute(
        select(GraphFactSource.source_kind, GraphFactSource.source_ref)
        .where(GraphFactSource.fact_id == fact_id)
        .order_by(GraphFactSource.source_kind, GraphFactSource.source_ref)
    )).all()
    return [{"kind": kind, "ref": ref} for kind, ref in rows]
