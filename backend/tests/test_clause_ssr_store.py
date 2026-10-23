"""OverGraph persistence for classifications, verifications, and anchors."""

from __future__ import annotations

from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.clause_ssr.anchors import (
    list_anchors,
    mark_stale_embeddings,
    promote_anchor,
    revoke_source_unit,
)
from app.services.clause_ssr.classifications import upsert_classification
from app.services.clause_ssr.queue import next_queue
from app.services.clause_ssr.sessions import apply_decision, undo_last
from app.services.clause_ssr.types import EmbeddingSpec
from app.services.clause_ssr.verifications import get_verification, record_decision
from tests.clause_ssr_fakes import embedding_spec, seed_units, unit_vector


def _classification(catalog, scope=None):
    return upsert_classification(
        catalog,
        scope=scope or shared_scope(),
        slug="termination",
        question="Är det här en uppsägningsklausul?",
        category="termination",
    )


def test_classification_round_trip(research_overgraph):
    catalog = research_overgraph
    first = _classification(catalog)
    again = _classification(catalog)
    assert first.id == again.id
    assert first.question.startswith("Är det här")
    changed = upsert_classification(
        catalog,
        scope=shared_scope(),
        slug="termination",
        question="Är detta en uppsägning?",
        category="termination",
    )
    assert changed.version == 2
    assert first.id != changed.id


def test_queue_reads_existing_text_units(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-a", "Avtalet kan sägas upp med tre månaders varsel.", unit_vector(0), "doc-1", 0),
        ("tu-b", "Priset är 12 000 kr per år.", unit_vector(1), "doc-1", 1),
        ("tu-dup", "Avtalet kan sägas upp med tre månaders varsel.", unit_vector(0), "doc-2", 0),
    ])
    classification = _classification(catalog)
    page = next_queue(
        catalog,
        scope=scope,
        classification_id=classification.id,
        reviewer_id="admin-1",
        limit=5,
    )
    assert [card.unit_id for card in page.cards] == ["tu-a", "tu-b"]
    assert page.remaining == 2


def test_yes_is_not_an_active_anchor(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-a", "Uppsägning sker skriftligen.", unit_vector(0), "doc-1", 0),
    ])
    classification = _classification(catalog)
    verification = record_decision(
        catalog,
        scope=scope,
        classification_id=classification.id,
        unit_id="tu-a",
        reviewer_id="admin-1",
        answer="yes",
    )
    assert verification.polarity == "positive"
    assert list_anchors(catalog, customer_id=None) == []
    promoted = promote_anchor(
        catalog, verification.id, scope=scope, embedding=embedding_spec(),
    )
    assert promoted.status == "draft"
    assert promoted.vector is not None


def test_no_is_not_generic_irrelevant(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-a", "Hyresgästen betalar hyran i förskott.", unit_vector(2), "doc-1", 0),
    ])
    classification = _classification(catalog)
    verification = record_decision(
        catalog,
        scope=scope,
        classification_id=classification.id,
        unit_id="tu-a",
        reviewer_id="admin-1",
        answer="no",
    )
    assert verification.polarity == "negative"
    assert verification.category == "termination"
    assert verification.question == classification.question
    assert verification.answer == "no"


def test_skip_and_unsure_are_not_labels(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-a", "Parterna är överens om tystnadsplikt.", unit_vector(3), "doc-1", 0),
        ("tu-b", "Avtalet förlängs automatiskt.", unit_vector(4), "doc-1", 1),
    ])
    classification = _classification(catalog)
    skip = record_decision(
        catalog, scope=scope, classification_id=classification.id,
        unit_id="tu-a", reviewer_id="admin-1", answer="skip",
    )
    unsure = record_decision(
        catalog, scope=scope, classification_id=classification.id,
        unit_id="tu-b", reviewer_id="admin-1", answer="unsure",
    )
    assert skip.polarity is None
    assert unsure.polarity is None
    try:
        promote_anchor(catalog, skip.id, scope=scope, embedding=embedding_spec())
    except ValueError as exc:
        assert "yes/no" in str(exc)
    else:
        raise AssertionError("skip must not become an anchor")


def test_decision_is_idempotent_and_revisable(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-a", "Uppsägningstiden är tre månader.", unit_vector(0), "doc-1", 0),
    ])
    classification = _classification(catalog)
    first = record_decision(
        catalog, scope=scope, classification_id=classification.id,
        unit_id="tu-a", reviewer_id="admin-1", answer="yes",
    )
    same = record_decision(
        catalog, scope=scope, classification_id=classification.id,
        unit_id="tu-a", reviewer_id="admin-1", answer="yes",
    )
    assert first.id == same.id
    assert same.revision == 1
    changed = record_decision(
        catalog, scope=scope, classification_id=classification.id,
        unit_id="tu-a", reviewer_id="admin-1", answer="no",
    )
    assert changed.id == first.id
    assert changed.revision == 2
    assert changed.answer == "no"
    assert get_verification(catalog, first.id).answer == "no"


def test_undo_revokes_last_and_returns_card(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-a", "Skriftlig uppsägning.", unit_vector(0), "doc-1", 0),
        ("tu-b", "Pris 100 kr.", unit_vector(1), "doc-1", 1),
    ])
    classification = _classification(catalog)
    page = next_queue(
        catalog, scope=scope, classification_id=classification.id, reviewer_id="admin-1",
    )
    verification = record_decision(
        catalog, scope=scope, classification_id=classification.id,
        unit_id="tu-a", reviewer_id="admin-1", answer="yes",
    )
    session = apply_decision(catalog, page.session, verification, scope=scope)
    session, unit_id = undo_last(catalog, session, scope=scope)
    assert unit_id == "tu-a"
    assert get_verification(catalog, verification.id).status == "revoked"
    again = next_queue(
        catalog, scope=scope, classification_id=classification.id, reviewer_id="admin-1",
    )
    assert again.cards[0].unit_id == "tu-a"


def test_source_revoke_and_embedding_model_change(research_overgraph):
    catalog = research_overgraph
    scope = shared_scope()
    seed_units(catalog, scope, [
        ("tu-a", "Uppsägning sker skriftligen.", unit_vector(0), "doc-1", 0),
    ])
    classification = _classification(catalog)
    verification = record_decision(
        catalog, scope=scope, classification_id=classification.id,
        unit_id="tu-a", reviewer_id="admin-1", answer="yes",
    )
    promote_anchor(catalog, verification.id, scope=scope, embedding=embedding_spec())
    stale = mark_stale_embeddings(
        catalog,
        scope=scope,
        expected=EmbeddingSpec(model="other-model", revision="v2", dimension=32),
    )
    assert stale == 1
    assert list_anchors(catalog, customer_id=None, statuses=("stale_embedding",))
    revoke_source_unit(catalog, "tu-a", scope=scope)
    assert list_anchors(catalog, customer_id=None, statuses=("source_revoked",))
    assert get_verification(catalog, verification.id).status == "revoked"


def test_customer_cannot_use_foreign_classification(research_overgraph):
    catalog = research_overgraph
    seed_units(catalog, customer_scope(2), [
        ("tu-x", "Hemligt.", unit_vector(0), "doc-x", 0),
    ])
    foreign = upsert_classification(
        catalog,
        scope=customer_scope(2),
        slug="price",
        question="Är det här en prisklausul?",
        category="price",
    )
    try:
        next_queue(
            catalog,
            scope=customer_scope(1),
            classification_id=foreign.id,
            reviewer_id="admin-1",
        )
    except PermissionError:
        return
    raise AssertionError("expected tenant isolation on classification")
