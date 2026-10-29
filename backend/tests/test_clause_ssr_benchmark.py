"""Scripted holdout benchmark. Not a live model-quality measurement."""

from __future__ import annotations

from app.services.knowledge.scope import shared_scope
from app.services.clause_ssr.anchors import promote_anchor
from app.services.clause_ssr.classifications import upsert_classification
from app.services.clause_ssr.benchmark import score_holdout
from app.services.clause_ssr.match import match_query
from app.services.clause_ssr.select import build_anchor_set
from app.services.clause_ssr.verifications import record_decision
from tests.clause_ssr_fakes import embedding_spec, near_vector, seed_units, unit_vector

# Golden clauses stay out of the selected AnchorSet.
HOLDOUT = ("gold-term", "gold-price", "gold-other")


def _seed(catalog) -> None:
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("lib-term-1", "Uppsägningstiden är tre månader.", unit_vector(0), "lib", 0),
        ("lib-term-2", "Skriftlig uppsägning krävs.", near_vector(0), "lib", 1),
        ("lib-price-1", "Priset är 10 000 kr per år.", unit_vector(10), "lib", 2),
        ("lib-price-2", "Årsavgiften faktureras i förskott.", near_vector(10), "lib", 3),
        ("gold-term", "Avtalet sägs upp med tre månaders varsel.", near_vector(0, 0.08), "gold", 0),
        ("gold-price", "Ersättningen är 10 000 kronor årligen.", near_vector(10, 0.08), "gold", 1),
        ("gold-other", "Tvist avgörs av svensk domstol.", unit_vector(20), "gold", 2),
    ])


def _library(catalog, labeled: int) -> None:
    scope = shared_scope()
    termination = upsert_classification(
        catalog,
        scope=scope,
        slug="termination",
        question="Är det här en uppsägningsklausul?",
        category="termination",
    )
    price = upsert_classification(
        catalog,
        scope=scope,
        slug="price",
        question="Är det här en prisklausul?",
        category="price",
    )
    pairs = [
        ("lib-term-1", termination.id, "yes"),
        ("lib-term-2", termination.id, "yes"),
        ("lib-price-1", price.id, "yes"),
        ("lib-price-2", price.id, "yes"),
    ]
    for unit_id, classification_id, answer in pairs[:labeled]:
        verification = record_decision(
            catalog,
            scope=scope,
            classification_id=classification_id,
            unit_id=unit_id,
            reviewer_id="bench",
            answer=answer,
        )
        promote_anchor(catalog, verification.id, scope=scope, embedding=embedding_spec())
    if labeled >= 2:
        build_anchor_set(
            catalog,
            scope=scope,
            category="termination",
            embedding=embedding_spec(),
            holdout_ids=HOLDOUT,
        )
    if labeled >= 4:
        build_anchor_set(
            catalog,
            scope=scope,
            category="price",
            embedding=embedding_spec(),
            holdout_ids=HOLDOUT,
        )


EXPECTED = {
    "gold-term": "termination",
    "gold-price": "price",
    "gold-other": None,
}


def test_clause_ssr_benchmark_scripted_holdout(research_overgraph):
    catalog = research_overgraph
    _seed(catalog)
    after: dict[int, dict[str, float | int]] = {}
    for labeled in (2, 4):
        _library(catalog, labeled)
        after[labeled] = score_holdout(
            catalog,
            scope=shared_scope(),
            embedding=embedding_spec(),
            expected=EXPECTED,
        )
    assert after[2]["precision_at_1"] >= 0.3
    assert after[4]["precision_at_1"] >= after[2]["precision_at_1"]
    assert after[4]["false_positives"] <= 1
    gold_term = match_query(
        catalog,
        scope=shared_scope(),
        embedding=embedding_spec(),
        text_unit_id="gold-term",
    )
    assert gold_term.top_k
    assert gold_term.top_k[0].source_unit_id != "gold-term"


def test_research_imports_ignore_clause_ssr():
    import app.services.research.execution as execution
    import app.services.research.swe_bridge as swe_bridge

    assert "clause_ssr" not in execution.__dict__
    assert "clause_ssr" not in swe_bridge.__dict__
