"""Opt-in clause SSR matching and AnchorSet selection."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.ssr.similarity import cosine_similarity
from app.services.clause_ssr.anchors import promote_anchor
from app.services.clause_ssr.classifications import upsert_classification
from app.services.clause_ssr.match import match_query
from app.services.clause_ssr.select import build_anchor_set, get_anchor_set
from app.services.clause_ssr.verifications import record_decision
from tests.clause_ssr_fakes import embedding_spec, near_vector, seed_units, unit_vector


@dataclass(frozen=True)
class _Label:
    slug: str
    unit_id: str
    answer: str
    question: str
    reviewer: str = "r1"


def _label(catalog, scope, spec: _Label):
    classification = upsert_classification(
        catalog, scope=scope, slug=spec.slug, question=spec.question, category=spec.slug,
    )
    verification = record_decision(
        catalog,
        scope=scope,
        classification_id=classification.id,
        unit_id=spec.unit_id,
        reviewer_id=spec.reviewer,
        answer=spec.answer,
    )
    promote_anchor(catalog, verification.id, scope=scope, embedding=embedding_spec())
    return classification


def test_match_uses_ssr_cosine_similarity():
    from app.services.clause_ssr import match as match_mod

    assert match_mod.cosine_similarity is cosine_similarity
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_match_reuses_text_unit_vector(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-term", "Uppsägningstiden är tre månader.", unit_vector(0), "doc-1", 0),
        ("tu-price", "Årspriset är 12 000 kronor.", unit_vector(7), "doc-1", 1),
        ("tu-query", "Skriftlig uppsägning med tre månaders varsel.", near_vector(0), "doc-2", 0),
    ])
    _label(catalog, scope, _Label(
        slug="termination", unit_id="tu-term", answer="yes",
        question="Är det här en uppsägningsklausul?",
    ))
    _label(catalog, scope, _Label(
        slug="price", unit_id="tu-price", answer="yes",
        question="Är det här en prisklausul?",
    ))
    build_anchor_set(
        catalog, scope=scope, category="termination", embedding=embedding_spec(),
    )
    build_anchor_set(
        catalog, scope=scope, category="price", embedding=embedding_spec(),
    )
    result = match_query(
        catalog,
        scope=scope,
        embedding=embedding_spec(),
        text_unit_id="tu-query",
        k=4,
    )
    assert result.top_k[0].category == "termination"
    assert result.top_k[0].cosine_similarity > 0.8
    assert result.abstained is False
    assert "termination" in result.labels
    assert result.category_scores[0].score <= 1.0


def test_negative_examples_and_multilabel_and_abstain(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-term", "Uppsägning sker skriftligen.", unit_vector(0), "doc-1", 0),
        ("tu-not", "Priset indexeras årligen.", unit_vector(8), "doc-1", 1),
        ("tu-query", "Indexklausul enligt KPI.", near_vector(8), "doc-2", 0),
        ("tu-far", "Parterna ska hålla förhandlingar.", unit_vector(15), "doc-3", 0),
    ])
    _label(catalog, scope, _Label(
        slug="termination", unit_id="tu-term", answer="yes",
        question="Är det här en uppsägningsklausul?",
    ))
    _label(catalog, scope, _Label(
        slug="termination", unit_id="tu-not", answer="no",
        question="Är det här en uppsägningsklausul?",
        reviewer="r2",
    ))
    build_anchor_set(
        catalog, scope=scope, category="termination", embedding=embedding_spec(),
    )
    negative = match_query(
        catalog, scope=scope, embedding=embedding_spec(), text_unit_id="tu-query",
    )
    assert negative.category_scores[0].negative_signal > 0.7
    far = match_query(
        catalog, scope=scope, embedding=embedding_spec(), text_unit_id="tu-far",
    )
    assert far.abstained is True
    assert far.labels == ()


def test_selection_is_reproducible_and_holds_out_golden(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    rows = [
        (f"tu-{index}", f"Klausul {index} om uppsägning.", unit_vector(index), "doc-1", index)
        for index in range(6)
    ]
    seed_units(catalog, scope, rows)
    classification = upsert_classification(
        catalog,
        scope=scope,
        slug="termination",
        question="Är det här en uppsägningsklausul?",
        category="termination",
    )
    for index in range(6):
        verification = record_decision(
            catalog,
            scope=scope,
            classification_id=classification.id,
            unit_id=f"tu-{index}",
            reviewer_id="r1",
            answer="yes",
        )
        promote_anchor(catalog, verification.id, scope=scope, embedding=embedding_spec())
    first = build_anchor_set(
        catalog,
        scope=scope,
        category="termination",
        embedding=embedding_spec(),
        holdout_ids=("tu-5",),
        max_per_polarity=4,
    )
    second = build_anchor_set(
        catalog,
        scope=scope,
        category="termination",
        embedding=embedding_spec(),
        holdout_ids=("tu-5",),
        max_per_polarity=4,
    )
    assert first.member_ids == second.member_ids
    assert "tu-5" not in {anchor_source(catalog, member) for member in first.member_ids}
    assert first.version + 1 == second.version
    assert get_anchor_set(catalog, first.id).status == "superseded"
    assert second.status == "active"


def anchor_source(catalog, anchor_id: str) -> str:
    from app.services.clause_ssr.anchors import get_anchor

    return get_anchor(catalog, anchor_id).source_unit_id


def test_match_does_not_leak_foreign_tenant(research_overgraph):
    catalog = research_overgraph
    seed_units(catalog, customer_scope(1), [
        ("tu-1", "Uppsägning kund 1.", unit_vector(0), "doc-1", 0),
        ("tu-q1", "Uppsägning liknande kund 1.", near_vector(0), "doc-1", 1),
    ])
    seed_units(catalog, customer_scope(2), [
        ("tu-2", "Uppsägning kund 2 hemlig.", unit_vector(0), "doc-2", 0),
    ])
    _label(catalog, customer_scope(2), _Label(
        slug="termination", unit_id="tu-2", answer="yes",
        question="Är det här en uppsägningsklausul?",
    ))
    build_anchor_set(
        catalog, scope=customer_scope(2), category="termination", embedding=embedding_spec(),
    )
    try:
        match_query(
            catalog,
            scope=customer_scope(1),
            embedding=embedding_spec(),
            text_unit_id="tu-q1",
        )
    except ValueError as exc:
        assert "no active anchor set" in str(exc)
    else:
        raise AssertionError("customer 1 must not see customer 2 anchors")


def test_clause_ssr_does_not_import_anchor_store():
    import app.services.clause_ssr.anchors as anchors
    import app.services.clause_ssr.match as match
    import app.services.clause_ssr.select as select

    for module in (anchors, match, select):
        assert "anchor_store" not in module.__dict__
        assert "SsrAnchorSet" not in inspect.getsource(module)
