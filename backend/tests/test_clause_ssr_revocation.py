"""Revocation must immediately remove promoted clause anchors from matching."""

from __future__ import annotations

import pytest

from app.services.knowledge.scope import shared_scope
from app.services.clause_ssr.anchors import promote_anchor
from app.services.clause_ssr.classifications import upsert_classification
from app.services.clause_ssr.match import match_query
from app.services.clause_ssr.queue import next_queue
from app.services.clause_ssr.select import build_anchor_set, get_anchor_set
from app.services.clause_ssr.sessions import apply_decision, undo_last
from app.services.clause_ssr.verifications import (
    get_verification,
    record_decision,
    revoke_verification,
)
from tests.clause_ssr_fakes import embedding_spec, near_vector, seed_units, unit_vector


def _classification(catalog, *, slug="termination", category="termination"):
    return upsert_classification(
        catalog,
        scope=shared_scope(),
        slug=slug,
        question=f"Är det här en {slug}-klausul?",
        category=category,
    )


def _promote(catalog, classification, unit_id, *, reviewer="admin-1", answer="yes"):
    verification = record_decision(
        catalog,
        scope=shared_scope(),
        classification_id=classification.id,
        unit_id=unit_id,
        reviewer_id=reviewer,
        answer=answer,
    )
    promote_anchor(catalog, verification.id, scope=shared_scope(), embedding=embedding_spec())
    return verification


def _units(catalog):
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-term", "Uppsägningstiden är tre månader.", unit_vector(0), "doc-1", 0),
        ("tu-price", "Årspriset är 12 000 kronor.", unit_vector(7), "doc-1", 1),
    ])


def _match(catalog, index=0):
    return match_query(
        catalog,
        scope=shared_scope(),
        embedding=embedding_spec(),
        vector=near_vector(index),
        k=8,
    )


def test_undo_revokes_promoted_anchor_and_active_set_member(research_overgraph):
    catalog = research_overgraph
    _units(catalog)
    classification = _classification(catalog)
    page = next_queue(
        catalog, scope=shared_scope(), classification_id=classification.id, reviewer_id="admin-1",
    )
    verification = _promote(catalog, classification, "tu-term")
    session = apply_decision(catalog, page.session, verification, scope=shared_scope())
    build_anchor_set(catalog, scope=shared_scope(), category="termination", embedding=embedding_spec())
    assert "termination" in _match(catalog).labels

    session, unit_id = undo_last(catalog, session, scope=shared_scope())
    assert unit_id == "tu-term"
    assert get_verification(catalog, verification.id).status == "revoked"
    assert get_anchor_set(catalog, list_sets(catalog)[0].id).member_ids == ()
    with pytest.raises(ValueError, match="no active anchor set"):
        _match(catalog)


def list_sets(catalog):
    from app.services.clause_ssr.select import list_anchor_sets
    return list_anchor_sets(catalog, customer_id=None, active_only=True)


@pytest.mark.parametrize("answer", ["no", "unsure"])
def test_answer_change_revokes_previous_positive_anchor(research_overgraph, answer):
    catalog = research_overgraph
    _units(catalog)
    classification = _classification(catalog)
    verification = _promote(catalog, classification, "tu-term")
    build_anchor_set(catalog, scope=shared_scope(), category="termination", embedding=embedding_spec())
    assert "termination" in _match(catalog).labels

    record_decision(
        catalog,
        scope=shared_scope(),
        classification_id=classification.id,
        unit_id="tu-term",
        reviewer_id="admin-1",
        answer=answer,
    )
    assert get_verification(catalog, verification.id).answer == answer
    with pytest.raises(ValueError, match="no active anchor set"):
        _match(catalog)


def test_revoke_verification_immediately_blocks_match(research_overgraph):
    catalog = research_overgraph
    _units(catalog)
    classification = _classification(catalog)
    verification = _promote(catalog, classification, "tu-term")
    build_anchor_set(catalog, scope=shared_scope(), category="termination", embedding=embedding_spec())
    assert "termination" in _match(catalog).labels

    revoke_verification(catalog, verification.id, scope=shared_scope())
    with pytest.raises(ValueError, match="no active anchor set"):
        _match(catalog)


def test_other_category_anchor_survives(research_overgraph):
    catalog = research_overgraph
    _units(catalog)
    termination = _classification(catalog)
    price = _classification(catalog, slug="price", category="price")
    term_verification = _promote(catalog, termination, "tu-term")
    _promote(catalog, price, "tu-price")
    build_anchor_set(catalog, scope=shared_scope(), category="termination", embedding=embedding_spec())
    build_anchor_set(catalog, scope=shared_scope(), category="price", embedding=embedding_spec())
    assert "price" in _match(catalog, 7).labels

    revoke_verification(catalog, term_verification.id, scope=shared_scope())
    result = _match(catalog, 7)
    assert "price" in result.labels
    assert "termination" not in _match(catalog, 0).labels


def test_promote_after_revoke_cannot_resurrect_anchor(research_overgraph):
    catalog = research_overgraph
    _units(catalog)
    classification = _classification(catalog)
    verification = record_decision(
        catalog,
        scope=shared_scope(),
        classification_id=classification.id,
        unit_id="tu-term",
        reviewer_id="admin-1",
        answer="yes",
    )
    revoke_verification(catalog, verification.id, scope=shared_scope())
    with pytest.raises(ValueError, match="only active|no longer active"):
        promote_anchor(catalog, verification.id, scope=shared_scope(), embedding=embedding_spec())


def test_read_guard_rejects_anchor_whose_verification_is_revoked(research_overgraph):
    from app.services.clause_ssr.anchors import anchor_is_matchable, list_anchors

    catalog = research_overgraph
    _units(catalog)
    classification = _classification(catalog)
    verification = _promote(catalog, classification, "tu-term")
    anchor = list_anchors(catalog, customer_id=None)[0]
    revoke_verification(catalog, verification.id, scope=shared_scope())
    assert anchor_is_matchable(catalog, anchor) is False


def test_promotion_recheck_blocks_revocation_during_write(research_overgraph, monkeypatch):
    from app.services.clause_ssr import anchors as anchors_mod

    catalog = research_overgraph
    _units(catalog)
    classification = _classification(catalog)
    verification = record_decision(
        catalog,
        scope=shared_scope(),
        classification_id=classification.id,
        unit_id="tu-term",
        reviewer_id="admin-1",
        answer="yes",
    )
    original = anchors_mod.get_verification
    calls = {"n": 0}

    def fake(catalog_arg, verification_id):
        calls["n"] += 1
        current = original(catalog_arg, verification_id)
        if calls["n"] == 1:
            return current
        return type(current)(**{**current.__dict__, "status": "revoked"})

    monkeypatch.setattr(anchors_mod, "get_verification", fake)
    with pytest.raises(ValueError, match="no longer active"):
        promote_anchor(catalog, verification.id, scope=shared_scope(), embedding=embedding_spec())
