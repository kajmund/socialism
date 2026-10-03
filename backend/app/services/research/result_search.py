"""Bounded, read-only traversal of question nodes to completed Graph answers."""

from dataclasses import dataclass, field
from time import perf_counter

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.graph_v2 import GraphFact, GraphFactQuestionDependency, GraphNode
from app.database.models import EvidenceSet, ExecutionAttempt, ExecutionRun
from app.services.graph_v2.retrieval import hybrid_facts
from app.services.knowledge.embeddings import EmbeddingProvider, require_embedding_vectors
from app.services.prompt_store import require_active_prompts
from app.services.research.answer_graph import ANSWER_PREDICATE
from app.services.research.graph_grounding import fact_is_current
from app.services.research.models import ResearchContext, ResearchNeed, utc_now
from app.services.research.result_judge import Coverage, ResultJudge
from app.services.research.result_store import SavedResearch, exact_answers, load_saved_answer

MAX_HOPS = 3
MAX_EDGES = 48
MAX_ANSWERS = 8


@dataclass
class ResultSearch:
    answer: SavedResearch | None = None
    match: str | None = None
    coverage: Coverage | None = None
    partial: list[SavedResearch] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    visited_edges: int = 0


async def find_completed_research(
    factory: async_sessionmaker[AsyncSession],
    need: ResearchNeed,
    scope: ResearchContext,
    context: dict,
    *,
    embeddings: EmbeddingProvider | None = None,
    judge: ResultJudge | None = None,
) -> ResultSearch:
    result = ResultSearch()
    started = perf_counter()
    async with factory() as session:
        ids = await exact_answers(session, need, scope)
        for fact_id in ids:
            saved = await load_saved_answer(session, fact_id, scope, now=utc_now())
            if (
                saved
                and saved.context == context
                and not (need.domains or need.modalities or need.capabilities)
            ):
                if all(item.source_type in {*need.source_types, "derived"} for item in saved.basis):
                    result.answer, result.match = saved, "exact"
                    break
    result.timings["exact_read_ms"] = (perf_counter() - started) * 1000
    if result.answer:
        return result
    await _nearby(factory, need, scope, context, result=result, embeddings=embeddings, judge=judge)
    return result


async def _seeds(session, need, scope, embeddings, *, vector) -> list[str]:
    hits = await hybrid_facts(
        session,
        customer_id=scope.scope.customer_id,
        query=need.question,
        embedding=vector,
        embedding_model=embeddings.model,
        limit=8,
    )
    valid = [hit.fact for hit in hits if fact_is_current(hit.fact, utc_now())]
    dependencies = list(
        await session.scalars(
            select(GraphFactQuestionDependency.question_node_id)
            .where(
                GraphFactQuestionDependency.fact_id.in_([fact.id for fact in valid]),
                GraphFactQuestionDependency.scope_key == f"customer:{scope.scope.customer_id}",
            )
            .limit(16)
        )
    )
    endpoints = {node for fact in valid for node in (fact.source_id, fact.target_id)}
    return list(
        await session.scalars(
            select(GraphNode.id)
            .where(
                GraphNode.id.in_(endpoints | set(dependencies)),
                GraphNode.node_type == "core.question",
                GraphNode.scope_key == f"customer:{scope.scope.customer_id}",
            )
            .order_by(GraphNode.id)
            .limit(8)
        )
    )


async def _frontier(session, frontier, scope, visited, *, remaining) -> list[dict]:
    rows = list(
        await session.scalars(
            select(GraphFact)
            .where(
                GraphFact.scope_key == f"customer:{scope.scope.customer_id}",
                GraphFact.status == "active",
                GraphFact.id.not_in(visited),
                GraphFact.predicate.in_((ANSWER_PREDICATE, "research.decomposed_to")),
                or_(GraphFact.source_id.in_(frontier), GraphFact.target_id.in_(frontier)),
            )
            .order_by(GraphFact.predicate, GraphFact.id)
            .limit(remaining)
        )
    )
    nodes = {
        node.id: node
        for node in await session.scalars(
            select(GraphNode).where(
                GraphNode.id.in_({ref for row in rows for ref in (row.source_id, row.target_id)}),
                GraphNode.scope_key == f"customer:{scope.scope.customer_id}",
            )
        )
    }
    return [
        {
            "id": row.id,
            "predicate": row.predicate,
            "source_id": row.source_id,
            "target_id": row.target_id,
            "source_question": nodes[row.source_id].name,
            "target_question": nodes[row.target_id].name,
        }
        for row in rows
        if fact_is_current(row, utc_now()) and row.source_id in nodes and row.target_id in nodes
    ]


async def _nearby(factory, need, scope, context, *, result, embeddings, judge) -> None:
    async with factory() as session:
        present = await session.scalar(
            select(GraphFact.id)
            .join(GraphNode, GraphNode.id == GraphFact.target_id)
            .join(
                EvidenceSet, EvidenceSet.id == GraphNode.attributes["evidence_set_id"].as_string()
            )
            .join(ExecutionAttempt, ExecutionAttempt.evidence_set_id == EvidenceSet.id)
            .join(ExecutionRun, ExecutionRun.id == EvidenceSet.run_id)
            .where(
                GraphFact.scope_key == f"customer:{scope.scope.customer_id}",
                GraphFact.predicate == ANSWER_PREDICATE,
                GraphFact.status == "active",
                ExecutionAttempt.status.in_(("ready", "completed")),
                ExecutionRun.customer_id == scope.scope.customer_id,
                ExecutionRun.module == scope.scope.module,
            )
            .limit(1)
        )
    if present is None:
        return
    if embeddings is None:
        from app.services.research.composition import research_embeddings

        embeddings = research_embeddings()
    started = perf_counter()
    vectors = require_embedding_vectors(
        await embeddings.embed([need.question]), dimension=embeddings.dimension
    )
    if len(vectors) != 1:
        raise ValueError("Result search requires one query embedding")
    result.timings["embedding_ms"] = (perf_counter() - started) * 1000
    async with factory() as session:
        frontier = await _seeds(session, need, scope, embeddings, vector=vectors[0])
        if not frontier:
            return
        if judge is None:
            prompts = await require_active_prompts(
                session,
                customer_id=scope.scope.customer_id,
                module=scope.scope.module,
                language="sv",
            )
            judge = ResultJudge(prompts)
    await _traverse(factory, need, scope, context, frontier=frontier, judge=judge, result=result)


async def _traverse(factory, need, scope, context, *, frontier, judge, result) -> None:
    visited_edges, visited_nodes, attempted_answers = set(), set(frontier), set()
    for _hop in range(MAX_HOPS):
        async with factory() as session:
            edges = await _frontier(
                session, frontier, scope, visited_edges, remaining=MAX_EDGES - len(visited_edges)
            )
        if not edges:
            break
        visited_edges.update(edge["id"] for edge in edges)
        result.visited_edges = len(visited_edges)
        started = perf_counter()
        allowed = await judge.navigate(need, context, edges)
        result.timings["navigation_ms"] = (
            result.timings.get("navigation_ms", 0) + (perf_counter() - started) * 1000
        )
        frontier = list(
            {
                ref
                for edge in edges
                if edge["id"] in allowed and edge["predicate"] != ANSWER_PREDICATE
                for ref in (edge["source_id"], edge["target_id"])
            }
            - visited_nodes
        )
        answer_ids = [
            edge["id"]
            for edge in edges
            if edge["id"] in allowed
            and edge["predicate"] == ANSWER_PREDICATE
            and edge["id"] not in attempted_answers
        ]
        for fact_id in answer_ids[: MAX_ANSWERS - len(attempted_answers)]:
            attempted_answers.add(fact_id)
            if await _check_answer(
                factory, need, scope, context, fact_id=fact_id, judge=judge, result=result
            ):
                return
        visited_nodes.update(frontier)
        if not frontier or len(visited_edges) >= MAX_EDGES or len(attempted_answers) >= MAX_ANSWERS:
            break


async def _check_answer(factory, need, scope, context, *, fact_id, judge, result) -> bool:
    async with factory() as session:
        saved = await load_saved_answer(session, fact_id, scope, now=utc_now())
    if saved is None:
        return False
    started = perf_counter()
    coverage = await judge.covers(need, context, saved)
    result.timings["coverage_ms"] = (
        result.timings.get("coverage_ms", 0) + (perf_counter() - started) * 1000
    )
    allowed_sources = all(
        item.source_type in {*need.source_types, "derived"} for item in saved.basis
    )
    if (
        coverage.outcome == "FULL"
        and coverage.confidence >= settings.research_jev_confidence_threshold
        and allowed_sources
    ):
        result.answer, result.match, result.coverage = saved, "nearby", coverage
        return True
    if coverage.outcome == "PARTIAL" or (coverage.outcome == "FULL" and not allowed_sources):
        result.partial.append(saved)
    return False
