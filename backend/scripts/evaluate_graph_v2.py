"""Evaluate Graph v2 projection against the recorded 36 § research scenario.

Run with ``uv run python scripts/evaluate_graph_v2.py``. This uses the existing
synthetic research fixture, SQLite, and deterministic vectors; it makes no model calls.
"""

import asyncio
import json
import os
from pathlib import Path

# Settings validation needs credentials even though this local evaluation uses none.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key-not-real")
os.environ.setdefault("CEREBRAS_API_KEY", "test-key-not-real")

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphFact, GraphFactSource, GraphNode
from app.database.models import Kund
from app.services.graph_v2.retrieval import hybrid_facts, neighbourhood
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.scope import customer_scope

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/research_eval/36_avtl.json"


async def evaluate() -> dict:
    scenario = json.loads(FIXTURE.read_text())
    entries = scenario["artifacts"]["claims"]
    sources = scenario["artifacts"]["domain_results"]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scope = customer_scope(1)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="Graph evaluation", slug="graph-eval", available_modules=[]))

    async def project(session):
        ids = {}
        for entry in entries:
            source = sources[entry["source_id"]]
            subject = await resolve_node(session, NodeInput(
                node_type="legal.source", name=entry["source_id"], scope=scope,
                identifier_namespace="legal.canonical_uri", identifier=source["source_uri"],
            ))
            slot = await resolve_node(session, NodeInput(
                node_type="core.attribute", name=entry["predicate"], scope=scope,
                identifier_namespace="legal.attribute",
                identifier=f"{source['source_uri']}:{entry['predicate']}",
            ))
            value = entry["value"]["value"]
            text = f"{entry['source_id']}: {str(value).lower()}"
            fact, _ = await resolve_fact(session, FactInput(
                source_id=subject.id, target_id=slot.id, scope=scope,
                predicate=entry["predicate"], fact_text=text,
                sources=(SourceRef("episode", entry["id"]),),
                embedding=(1.0, 0.0), embedding_model="eval-deterministic",
            ))
            ids[entry["id"]] = fact.id
        return ids

    async with factory.begin() as session:
        ids = await project(session)
        first = await _counts(session)
    async with factory.begin() as session:
        assert ids == await project(session)
        replay = await _counts(session)
        hits = {}
        for entry in entries:
            query = str(entry["value"]["value"]).lower()
            result = await hybrid_facts(session, customer_id=1, query=query, limit=3)
            hits[entry["id"]] = ids[entry["id"]] in {hit.fact.id for hit in result}
        source = await session.scalar(select(GraphNode).where(
            GraphNode.identity_key == "legal.canonical_uri:fixture://case/positive",
        ))
        neighbours = await neighbourhood(session, customer_id=1, seeds=[source.id], max_hops=2)
        reachable = {hit.fact.id for hit in neighbours}
        multi = all(ids[key] in reachable for key in ("positive", "term_type", "commercial"))
        isolated = await hybrid_facts(session, customer_id=2, query="liability_cap")
    await engine.dispose()
    return {
        "scenario": "36_avtl", "claims": len(entries),
        "first_pass": first, "replay": replay,
        "growth_on_replay": {key: replay[key] - first[key] for key in first},
        "lexical_recall_at_3": {"hits": sum(hits.values()), "total": len(hits)},
        "positive_case_three_facts_reachable_in_two_hops": multi,
        "other_tenant_hits": len(isolated),
    }


async def _counts(session):
    return {
        "nodes": await session.scalar(select(func.count()).select_from(GraphNode)),
        "facts": await session.scalar(select(func.count()).select_from(GraphFact)),
        "provenance": await session.scalar(select(func.count()).select_from(GraphFactSource)),
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))
