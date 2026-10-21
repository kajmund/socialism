"""Benchmark answer lookup: legacy SQL join vs the OverGraph reader (slice 1).

Measures warm latency for the two lookup primitives that dominate
``answer_graph.lookup_answers``: resolving a canonical question to its active answer
facts and reading the answer node's basis. Read-only: temp directories only.

Usage:
    uv run python scripts/benchmark_answer_lookup.py [--answers N] [--iters N]
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import create_engine

from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.publish import AnswerPublish, publish_answer_fact
from app.services.overgraph.answers import answer_facts, entity_attributes

CUSTOMER = 7
QUESTION = "Vad gäller uppsägningstiden?"


def _latency_ms(fn, iters: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iters):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def _p(samples: list[float], q: float) -> float:
    return float(statistics.quantiles(samples, n=100, method="inclusive")[int(q * 100) - 1])


def _summary(name: str, samples: list[float]) -> str:
    return (
        f"{name:22} p50={statistics.median(samples):7.3f} ms  "
        f"p95={_p(samples, 0.95):7.3f} ms  max={max(samples):7.3f} ms"
    )


def _seed_overgraph(catalog, answers: int) -> str:
    question_id = f"question-{CUSTOMER}"
    for index in range(answers):
        publish_answer_fact(
            catalog,
            AnswerPublish(
                question_id=question_id,
                question_text=QUESTION,
                scope=customer_scope(CUSTOMER),
                identity=f"answer-{index}",
                evidence_set_id=f"set-{index}",
                fact_id=f"fact-{index}",
                attributes={"knowledge_module": "dd", "answer_status": "sufficient"},
                basis=[{"title": f"Svar {index}"}],
                assessment={"sufficient": True},
                dependency_ids=(),
            ),
        )
    return question_id


def _seed_sql(engine, answers: int) -> None:
    metadata = sa.MetaData()
    facts = sa.Table(
        "graph_facts", metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), index=True),
        sa.Column("target_id", sa.String(64)),
        sa.Column("scope_key", sa.String(64)),
        sa.Column("predicate", sa.String(64)),
        sa.Column("status", sa.String(32)),
        sa.Column("created_at", sa.DateTime),
    )
    nodes = sa.Table(
        "graph_nodes", metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("node_type", sa.String(64)),
        sa.Column("scope_key", sa.String(64)),
        sa.Column("attributes", sa.JSON),
    )
    identifiers = sa.Table(
        "graph_identifiers", metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("node_id", sa.String(64), index=True),
        sa.Column("scope_key", sa.String(64)),
        sa.Column("namespace", sa.String(64)),
        sa.Column("identifier", sa.String(64)),
    )
    questions = sa.Table(
        "knowledge_questions", metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64)),
        sa.Column("identity_key", sa.String(64)),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(nodes.insert(), [
            {"id": "question", "node_type": "core.question",
             "scope_key": f"customer:{CUSTOMER}", "attributes": {}},
            *[
                {"id": f"answer-{index}", "node_type": "research.answer",
                 "scope_key": f"customer:{CUSTOMER}", "attributes": {"basis": [{"title": "x"}]}}
                for index in range(answers)
            ],
        ])
        connection.execute(identifiers.insert(), {
            "id": "ident-question", "node_id": "question",
            "scope_key": f"customer:{CUSTOMER}",
            "namespace": "research.question_id", "identifier": "knowledge-question",
        })
        connection.execute(questions.insert(), {
            "id": "knowledge-question", "scope_key": f"customer:{CUSTOMER}",
            "identity_key": "question-identity",
        })
        connection.execute(facts.insert(), [
            {"id": f"fact-{index}", "source_id": "question", "target_id": f"answer-{index}",
             "scope_key": f"customer:{CUSTOMER}", "predicate": "research.answered_by",
             "status": "active", "created_at": datetime.now(UTC)}
            for index in range(answers)
        ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=int, default=50)
    parser.add_argument("--iters", type=int, default=200)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="answer-lookup-bench-"))
    try:
        catalog = open_catalog(root / "knowledge", kind="knowledge", dimension=64)
        question_id = _seed_overgraph(catalog, args.answers)

        def overgraph_lookup() -> int:
            facts = answer_facts(catalog, question_id, CUSTOMER)
            for fact in facts:
                entity_attributes(catalog, fact.target_id)
            return len(facts)

        sql_engine = create_engine(f"sqlite:///{root / 'mirror.db'}")
        _seed_sql(sql_engine, args.answers)
        fact_table = sa.Table("graph_facts", sa.MetaData(), autoload_with=sql_engine)
        node_table = sa.Table("graph_nodes", sa.MetaData(), autoload_with=sql_engine)

        def sql_lookup() -> int:
            with sql_engine.connect() as connection:
                rows = connection.execute(
                    sa.select(fact_table.c.id, node_table.c.attributes)
                    .join(node_table, node_table.c.id == fact_table.c.target_id)
                    .where(
                        fact_table.c.source_id == "question",
                        fact_table.c.scope_key.in_(("shared", f"customer:{CUSTOMER}")),
                        fact_table.c.predicate == "research.answered_by",
                        node_table.c.node_type == "research.answer",
                        fact_table.c.status == "active",
                    )
                    .order_by(fact_table.c.created_at.desc())
                ).all()
            return len(rows)

        identifiers_table = sa.Table("graph_identifiers", sa.MetaData(), autoload_with=sql_engine)
        questions_table = sa.Table("knowledge_questions", sa.MetaData(), autoload_with=sql_engine)
        exact_scope = f"customer:{CUSTOMER}"

        def overgraph_exact_answers() -> int:
            facts = answer_facts(
                catalog, f"question-{CUSTOMER}", CUSTOMER,
                limit=8, exact_scope=exact_scope,
            )
            return len(facts)

        def sql_exact_answers() -> int:
            with sql_engine.connect() as connection:
                rows = connection.execute(
                    sa.select(fact_table.c.id)
                    .join(identifiers_table, identifiers_table.c.node_id == fact_table.c.source_id)
                    .join(questions_table, questions_table.c.id == identifiers_table.c.identifier)
                    .where(
                        fact_table.c.scope_key == exact_scope,
                        identifiers_table.c.scope_key == fact_table.c.scope_key,
                        identifiers_table.c.namespace == "research.question_id",
                        questions_table.c.scope_key == fact_table.c.scope_key,
                        questions_table.c.identity_key == "question-identity",
                        fact_table.c.predicate == "research.answered_by",
                        fact_table.c.status == "active",
                    )
                    .order_by(fact_table.c.created_at.desc(), fact_table.c.id)
                    .limit(8)
                ).all()
            return len(rows)

        assert overgraph_exact_answers() == min(args.answers, 8)
        assert sql_exact_answers() == min(args.answers, 8)
        print(_summary("overgraph exact_answers", _latency_ms(overgraph_exact_answers, args.iters)))
        print(_summary("sql exact_answers", _latency_ms(sql_exact_answers, args.iters)))
        print(f"answers={args.answers} iters={args.iters}")
        print(_summary("overgraph answer_facts", _latency_ms(overgraph_lookup, args.iters)))
        print(_summary("sql join (legacy)", _latency_ms(sql_lookup, args.iters)))
        catalog.close()
        sql_engine.dispose()
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
