"""Bounded, read-only traversal of question nodes to completed Graph answers."""

import asyncio
import json
from dataclasses import dataclass, field
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.models import EvidenceSet, ExecutionAttempt, ExecutionRun
from app.services.overgraph.labels import (
    ENTITY,
    FACT,
    OBJECT,
    SUBJECT,
    scope_label,
    visible_scope_keys,
)
from app.services.knowledge.embeddings import EmbeddingProvider, require_embedding_vectors
from app.services.prompt_store import require_active_prompts
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.hybrid_retrieval import hybrid_fact_hits
from app.services.overgraph.labels import DEPENDS_ON
from app.services.overgraph.research import QUESTION_TYPE
from app.services.research.answer_graph import ANSWER_PREDICATE
from app.services.retrieval_index import require_current_index
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
        now = utc_now()
        ids = await exact_answers(session, need, scope, now=now)
        for fact_id in ids:
            saved = await load_saved_answer(session, fact_id, scope, now=now)
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


def _graph_seeds(catalog, index, question: str, customer_id: int, *, vector) -> dict[str, list[str]]:
    """Hybrid fact hits plus their endpoints and question dependencies (OverGraph only)."""
    hits = hybrid_fact_hits(
        catalog, index, customer_id=customer_id, query=question,
        limit=8, dense_query=list(vector) if vector is not None else None,
    )
    endpoints: set[str] = set()
    dependencies: set[str] = set()
    for hit in hits:
        endpoints.update((hit.fact.source_id, hit.fact.target_id))
        row = catalog.get_by_key(FACT, hit.fact.id)
        if row is None or row.engine_id is None:
            continue
        for engine_id in catalog.neighbors(
            row.engine_id, direction="incoming", edge_label_filter=[DEPENDS_ON],
        ):
            question_row = catalog.get(engine_id)
            if question_row is not None:
                dependencies.add(question_row.key)
    return {"endpoints": sorted(endpoints), "dependencies": sorted(dependencies)}


def _question_seeds(catalog, keys: list[str], scope_key: str) -> list[str]:
    seeds: list[str] = []
    for key in sorted(set(keys)):
        row = catalog.get_by_key(ENTITY, key)
        if row is None:
            continue
        if str(row.props.get("node_type") or "") != QUESTION_TYPE:
            continue
        if str(row.props.get("scope_key") or "") != scope_key:
            continue
        seeds.append(key)
    return seeds[:8]


async def _seeds(session, need, scope, embeddings, *, vector) -> list[str]:
    catalog = require_knowledge()
    index = await asyncio.to_thread(require_current_index)
    customer_id = scope.scope.customer_id
    collected = await asyncio.to_thread(
        _graph_seeds, catalog, index, need.question, customer_id, vector=vector,
    )
    scope_key = f"customer:{customer_id}"
    return _question_seeds(
        catalog, collected["endpoints"] + collected["dependencies"], scope_key,
    )


FRONTIER_PREDICATES = (ANSWER_PREDICATE, "research.decomposed_to")
ANSWER_ATTRS_EVIDENCE_SET = "evidence_set_id"


def _in_visible_scope(props, visible: set[str]) -> bool:
    return str(props.get("scope_key") or "") in visible


def _frontier_fact(fact, *, visible: set[str], visited: set[str], found: dict) -> bool:
    if fact is None or str(fact.key) in visited or str(fact.key) in found:
        return False
    if not _in_visible_scope(fact.props, visible):
        return False
    if str(fact.props.get("status") or "active") != "active":
        return False
    return str(fact.props.get("predicate") or "") in FRONTIER_PREDICATES


def _frontier_row(catalog, fact, visible: set[str]) -> dict | None:
    source = catalog.get_by_key(ENTITY, str(fact.props.get("source_key") or ""))
    target = catalog.get_by_key(ENTITY, str(fact.props.get("target_key") or ""))
    if source is None or target is None:
        return None
    if not _in_visible_scope(source.props, visible) or not _in_visible_scope(target.props, visible):
        return None
    return {
        "id": str(fact.key),
        "predicate": str(fact.props.get("predicate") or ""),
        "source_id": str(source.key),
        "target_id": str(target.key),
        "source_question": str(source.props.get("name") or ""),
        "target_question": str(target.props.get("name") or ""),
    }


def _frontier_rows(catalog, *, customer_id: int, frontier: list[str], visited: set[str], remaining: int) -> list[dict]:
    """Neighbouring answer/decomposition facts, read from OverGraph."""
    visible = set(visible_scope_keys(customer_id))
    found: dict[str, object] = {}
    for node_key in sorted(frontier):
        node = catalog.get_by_key(ENTITY, node_key)
        if node is None or node.engine_id is None:
            continue
        for fact_id in catalog.neighbors(
            node.engine_id, direction="incoming", edge_label_filter=[SUBJECT, OBJECT],
        ):
            fact = catalog.get(fact_id)
            if _frontier_fact(fact, visible=visible, visited=visited, found=found):
                found[str(fact.key)] = fact
    rows: list[dict] = []
    for key in sorted(found, key=lambda item: (str(found[item].props.get("predicate")), item)):
        row = _frontier_row(catalog, found[key], visible)
        if row is None:
            continue
        rows.append(row)
        if len(rows) >= remaining:
            break
    return rows


async def _frontier(session, frontier, scope, visited, *, remaining) -> list[dict]:
    catalog = require_knowledge()
    return await asyncio.to_thread(
        _frontier_rows, catalog,
        customer_id=scope.scope.customer_id,
        frontier=list(frontier), visited=set(visited), remaining=remaining,
    )


async def _completed_evidence_sets(session, scope) -> set[str]:
    """Evidence sets of ready/completed attempts for this customer and module."""
    rows = await session.execute(
        select(EvidenceSet.id)
        .join(ExecutionAttempt, ExecutionAttempt.evidence_set_id == EvidenceSet.id)
        .join(ExecutionRun, ExecutionRun.id == EvidenceSet.run_id)
        .where(
            ExecutionAttempt.status.in_(("ready", "completed")),
            ExecutionRun.customer_id == scope.scope.customer_id,
            ExecutionRun.module == scope.scope.module,
        )
        .limit(200)
    )
    return {row[0] for row in rows.all()}


def _answer_target_in_sets(catalog, customer_id: int, set_ids: set[str]) -> bool:
    """Any answer fact whose target node belongs to a completed evidence set."""
    for scope_key in visible_scope_keys(customer_id):
        nodes, _ = catalog.query_nodes(
            label_filter={"labels": [FACT, scope_label(scope_key)], "mode": "all"},
            limit=500,
        )
        for node in nodes:
            if str(node.props.get("predicate") or "") != ANSWER_PREDICATE:
                continue
            target = catalog.get_by_key(ENTITY, str(node.props.get("target_key") or ""))
            if target is None:
                continue
            attributes = json.loads(str(target.props.get("attributes_json") or "{}"))
            if str(attributes.get(ANSWER_ATTRS_EVIDENCE_SET) or "") in set_ids:
                return True
    return False


async def _nearby(factory, need, scope, context, *, result, embeddings, judge) -> None:
    async with factory() as session:
        completed = await _completed_evidence_sets(session, scope)
    if not completed:
        return
    present = await asyncio.to_thread(
        _answer_target_in_sets, require_knowledge(), scope.scope.customer_id, completed,
    )
    if not present:
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
