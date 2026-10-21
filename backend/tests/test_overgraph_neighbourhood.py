"""Bounded fact traversal: hops, 1/hop scores, validity at each step, cycles, determinism."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.graph_v2.types import FactInput, NodeInput
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.neighbourhood import neighbourhood_facts
from app.services.overgraph.research import update_fact
from app.services.overgraph.write import upsert_entity, write_fact

CUSTOMER = 5
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _entity(name: str, customer_id: int = CUSTOMER) -> str:
    return upsert_entity(require_knowledge(), NodeInput(
        node_type="core.concept", name=name, scope=customer_scope(customer_id),
    )).key


def _fact(fact_id: str, source: str, target: str, customer_id: int = CUSTOMER) -> None:
    write_fact(
        require_knowledge(),
        FactInput(
            source_id=source, target_id=target, scope=customer_scope(customer_id),
            predicate="legal.rule", fact_text=f"rule {fact_id}", sources=(),
        ),
        key=fact_id,
    )


def _traverse(seeds, *, max_hops=3, limit=100):
    return neighbourhood_facts(
        require_knowledge(), customer_id=CUSTOMER, seeds=seeds,
        max_hops=max_hops, limit=limit, now=NOW,
    )


@pytest.fixture
def chain():
    """e1 -f1-> e2 -f2-> e3 -f3-> e4."""
    e1, e2, e3, e4 = (_entity(name) for name in ("e1", "e2", "e3", "e4"))
    _fact("f1", e1, e2)
    _fact("f2", e2, e3)
    _fact("f3", e3, e4)
    return e1, e2, e3, e4


def test_hops_and_one_over_hop_scores(chain):
    e1, _e2, _e3, _e4 = chain
    hits = _traverse([e1])
    assert [(hit.fact.id, hit.hop) for hit in hits] == [("f1", 1), ("f2", 2), ("f3", 3)]
    assert [hit.score for hit in hits] == pytest.approx([1.0, 0.5, 1 / 3])


def test_invalid_intermediate_fact_never_opens_the_path(chain):
    e1, _e2, _e3, _e4 = chain
    update_fact(require_knowledge(), "f1", invalid_at=NOW - timedelta(days=1))
    assert _traverse([e1]) == []


def test_superseded_intermediate_fact_never_opens_the_path(chain):
    e1, _e2, _e3, _e4 = chain
    update_fact(require_knowledge(), "f1", status="superseded")
    assert _traverse([e1]) == []


def test_a_fact_reachable_twice_appears_once_with_the_shortest_hop():
    e1, e2, e3 = (_entity(name) for name in ("c1", "c2", "c3"))
    _fact("direct", e1, e3)
    _fact("via", e1, e2)
    _fact("onward", e2, e3)
    _fact("loop", e3, e1)
    hits = _traverse([e1])
    ids = [hit.fact.id for hit in hits]
    assert len(ids) == len(set(ids)), "a fact must appear at most once"
    assert [item for item in ids if item == "direct"] == ["direct"]
    assert next(hit.hop for hit in hits if hit.fact.id == "direct") == 1
    assert next(hit.hop for hit in hits if hit.fact.id == "onward") == 2


def test_cycles_terminate_and_stay_deterministic(chain):
    _e1, _e2, _e3, e4 = chain
    _fact("back", e4, chain[0])
    first = [(hit.fact.id, hit.hop) for hit in _traverse([chain[0]])]
    second = [(hit.fact.id, hit.hop) for hit in _traverse([chain[0]])]
    assert first == second
    assert len({fact_id for fact_id, _hop in first}) == len(first)


def test_invalid_facts_are_filtered_before_the_budget(chain):
    e1, _e2, _e3, _e4 = chain
    update_fact(require_knowledge(), "f1", invalid_at=NOW - timedelta(days=1))
    _fact("sibling", e1, _entity("sibling"))
    hits = _traverse([e1], limit=1)
    assert [hit.fact.id for hit in hits] == ["sibling"]


def test_fact_from_another_tenant_is_never_traversed(chain):
    e1, _e2, _e3, _e4 = chain
    foreign_source = _entity("foreign-source", customer_id=99)
    foreign_target = _entity("foreign-target", customer_id=99)
    _fact("foreign", foreign_source, foreign_target, customer_id=99)
    assert _traverse([foreign_source]) == []
    assert {hit.fact.id for hit in _traverse([e1])} == {"f1", "f2", "f3"}

