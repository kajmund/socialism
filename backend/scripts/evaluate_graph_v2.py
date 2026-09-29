"""Evaluate Graph v2 projection against the recorded 36 § research scenario.

Run with ``uv run python scripts/evaluate_graph_v2.py``. This uses the existing
synthetic research fixture, SQLite, and deterministic vectors; it makes no model calls.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphFact, GraphFactSource, GraphNode
from app.database.models import Kund
from app.services.graph_v2.legal_writeback import value_node_input
from app.services.graph_v2.retrieval import hybrid_facts, neighbourhood
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.scope import customer_scope

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/research_eval/36_avtl.json"


class ExactValueJudge:
    async def same_node(self, proposed, candidate_name):
        return proposed.name.casefold() == candidate_name.casefold()


async def evaluate() -> dict:
    scenario = json.loads(FIXTURE.read_text())
    recorded = scenario["artifacts"]["claims"]
    entries = [*recorded, *(
        {"id": f"{source_id}_protection", "source_id": source_id,
         "predicate": "legal.consumer_protection", "value": {"value": True}}
        for source_id in ("prop_1975_76_81", "statute_36")
    )]
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
            claim = KnowledgeClaim(
                id=entry["id"], customer_id=1, predicate=entry["predicate"],
                value=entry["value"], supporting_text_unit_ids=(),
            )
            target = await resolve_node(
                session, value_node_input(claim, scope), judge=ExactValueJudge(),
            )
            value = entry["value"]["value"]
            text = f"{entry['source_id']} — {entry['predicate']}: {str(value).lower()}"
            fact, _ = await resolve_fact(session, FactInput(
                source_id=subject.id, target_id=target.id, scope=scope,
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
        for entry in recorded:
            query = str(entry["value"]["value"]).lower()
            result = await hybrid_facts(session, customer_id=1, query=query, limit=3)
            hits[entry["id"]] = ids[entry["id"]] in {hit.fact.id for hit in result}
        proposition = await session.scalar(select(GraphNode).where(
            GraphNode.identity_key == "legal.canonical_uri:fixture://prop/1975-76-81",
        ))
        cross_source = await neighbourhood(
            session, customer_id=1, seeds=[proposition.id], max_hops=2,
        )
        cross_reachable = ids["statute_36_protection"] in {
            hit.fact.id for hit in cross_source
        }
        proposition_fact = await session.get(GraphFact, ids["prop_1975_76_81_protection"])
        statute_fact = await session.get(GraphFact, ids["statute_36_protection"])
        shared_value = await session.get(GraphNode, proposition_fact.target_id)
        statute_source = await session.get(GraphNode, statute_fact.source_id)
        statute_hit = next(
            (hit for hit in cross_source if hit.fact.id == statute_fact.id), None,
        )
        cross_path = bool(
            statute_hit is not None and statute_hit.hop == 2
            and proposition_fact.source_id == proposition.id
            and statute_fact.source_id == statute_source.id
            and proposition.id != statute_source.id
            and proposition_fact.target_id == statute_fact.target_id
        )
        isolated = await hybrid_facts(session, customer_id=2, query="liability_cap")
    await engine.dispose()
    return {
        "scenario": "36_avtl", "recorded_claims": len(recorded),
        "projected_facts": len(entries),
        "first_pass": first, "replay": replay,
        "growth_on_replay": {key: replay[key] - first[key] for key in first},
        "lexical_recall_at_3": {"hits": sum(hits.values()), "total": len(hits)},
        "cross_source_two_hop": cross_reachable and cross_path,
        "multi_hop_path": {
            "from": proposition.name,
            "via": f"{shared_value.node_type}:{shared_value.name}",
            "to": statute_source.name,
            "hops": statute_hit.hop if statute_hit is not None else None,
        },
        "shared_consumer_protection_value": proposition_fact.target_id == statute_fact.target_id,
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
