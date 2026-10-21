"""Logical claim identity with per-document evidence links.

Regression cover for the package-4 rules: one claim node for many documents, per-document
evidence removal, "no longer verified" never becoming a negative claim, and no CONTRADICTS
edge for an UNSUPPORTED verification.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.knowledge.units import hash_text
from app.services.overgraph.claims import (
    VerificationObservationWrite,
    upsert_verification_observation,
)
from app.services.overgraph.labels import CONTRADICTS
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.write import upsert_text_unit
from app.services.overgraph.legal_claims import (
    VERIFIED,
    Support,
    add_support,
    claim_is_verified,
    support_is_valid,
    evidence_links,
    legal_claim_key,
    link_evidence,
    unlink_document_version,
    supporting_text_units,
    upsert_legal_claim,
)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
SCOPE = customer_scope(4)
PREDICATE = "contract.termination.notice_period"
VALUE = {"months": 9}


def _text_unit(unit_id: str) -> str:
    text = f"Klausul {unit_id} om uppsägningstid."
    upsert_text_unit(require_knowledge(), TextUnitWrite(
        unit_id=unit_id, scope=SCOPE, document_id="doc-1", document_version_id="v1",
        text=text, content_hash=hash_text(text), ordinal=0,
    ))
    return unit_id


def _support(claim_key: str, version: str, unit_id: str, **kwargs) -> None:
    link_evidence(
        require_knowledge(), claim_key=claim_key, document_version_id=version,
        text_unit_ids=(unit_id,), **kwargs,
    )
    add_support(
        require_knowledge(), claim_key=claim_key, document_version_id=version,
        support=Support(
            text_unit_id=_text_unit(unit_id),
            valid_from=kwargs.get("valid_from"),
            valid_to=kwargs.get("valid_to"),
            decision=kwargs.get("decision", VERIFIED),
        ),
    )


def _claim():
    return upsert_legal_claim(
        require_knowledge(), scope=SCOPE, predicate=PREDICATE, value=VALUE,
    )


def test_one_claim_node_for_many_documents_that_agree():
    claim = _claim()
    assert claim.key == legal_claim_key(SCOPE, PREDICATE, VALUE)
    for version in ("v1", "v2", "v3"):
        _support(claim.key, version, f"tu-{version}")
    rebuilt = _claim()
    assert rebuilt.key == claim.key, "a second source must not mint a second claim node"
    links = evidence_links(require_knowledge(), claim.key)
    assert [str(link.props["document_version_id"]) for link in links] == ["v3", "v2", "v1"]
    assert claim_is_verified(require_knowledge(), claim.key, now=NOW) is True


def test_removing_one_document_keeps_the_claim_and_the_other_support():
    claim = _claim()
    for version in ("v1", "v2", "v3"):
        _support(claim.key, version, f"tu-{version}")
    assert unlink_document_version(
        require_knowledge(), claim_key=claim.key, document_version_id="v2",
    ) is True
    remaining = evidence_links(require_knowledge(), claim.key)
    assert [str(link.props["document_version_id"]) for link in remaining] == ["v3", "v1"]
    assert require_knowledge().get_by_key("Claim", claim.key) is not None
    assert claim_is_verified(require_knowledge(), claim.key, now=NOW) is True


def test_losing_the_last_evidence_link_is_not_verified_but_still_no_negative_claim():
    claim = _claim()
    _support(claim.key, "v1", "tu-v1")
    unlink_document_version(require_knowledge(), claim_key=claim.key, document_version_id="v1")
    assert evidence_links(require_knowledge(), claim.key) == []
    assert claim_is_verified(require_knowledge(), claim.key, now=NOW) is False
    still_there = require_knowledge().get_by_key("Claim", claim.key)
    assert still_there is not None, "the claim node must not disappear with its evidence"
    assert still_there.props["status"] == "active"
    # No inverse/negative claim may be minted from missing evidence.
    assert require_knowledge().get_by_key(
        "Claim", legal_claim_key(SCOPE, PREDICATE, {"months": -9}),
    ) is None


def test_evidence_validity_window_expires_verification():
    claim = _claim()
    _support(claim.key, "v1", "tu-expired", valid_to=NOW - timedelta(days=1))
    assert claim_is_verified(require_knowledge(), claim.key, now=NOW) is False


def test_unsupported_verification_does_not_create_a_contradiction_edge():
    catalog = require_knowledge()
    _claim()
    before = catalog.count_edges_by_label(CONTRADICTS)
    upsert_verification_observation(
        catalog,
        VerificationObservationWrite(
            class_id=PREDICATE,
            document_id="doc-1",
            document_version_id="v1",
            value=VALUE,
            polarity="affirmed",
            taxonomy_version="v1",
            scope=SCOPE,
            kind="jev_verification",
            decision="UNSUPPORTED",
            reason_code="no_supporting_passage",
        ),
    )
    assert catalog.count_edges_by_label(CONTRADICTS) == before


def test_two_independent_supports_in_one_document_version_expire_separately():
    """One clause expiring must not invalidate another clause from the same version."""
    claim = _claim()
    link_evidence(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        text_unit_ids=("tu-a", "tu-b"),
    )
    add_support(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        support=Support(
            text_unit_id=_text_unit("tu-a"), valid_to=NOW - timedelta(days=1), decision=VERIFIED,
        ),
    )
    add_support(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        support=Support(text_unit_id=_text_unit("tu-b"), decision=VERIFIED),
    )
    assert claim_is_verified(require_knowledge(), claim.key, now=NOW) is True
    assert support_is_valid(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        text_unit_id="tu-a", now=NOW,
    ) is False
    assert support_is_valid(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        text_unit_id="tu-b", now=NOW,
    ) is True


def test_logical_claims_and_document_properties_do_not_share_a_label():
    """Two identity rules under one node type are not acceptable."""
    from app.services.overgraph.labels import CLAIM, DOCUMENT_PROPERTY

    assert CLAIM != DOCUMENT_PROPERTY
    legal = _claim()
    assert CLAIM in legal.labels and DOCUMENT_PROPERTY not in legal.labels


def test_a_lexical_candidate_never_verifies_a_claim():
    """A support edge without a Jev SUPPORTED verdict is not verified evidence."""
    claim = _claim()
    link_evidence(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        text_unit_ids=("tu-candidate",),
    )
    add_support(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        support=Support(text_unit_id=_text_unit("tu-candidate")),
    )
    assert claim_is_verified(require_knowledge(), claim.key, now=NOW) is False, (
        "a lexically discovered candidate must not count as legal verification"
    )
    assert support_is_valid(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        text_unit_id="tu-candidate", now=NOW, require_verified=False,
    ) is True


def test_undecided_verification_does_not_verify_either():
    claim = _claim()
    link_evidence(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        text_unit_ids=("tu-undecided",),
    )
    add_support(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        support=Support(text_unit_id=_text_unit("tu-undecided"), decision="UNDECIDED"),
    )
    assert claim_is_verified(require_knowledge(), claim.key, now=NOW) is False


def test_support_edge_keeps_verification_version_and_source_ref():
    """SUPPORTED is a Jev verdict, not a truth guarantee: keep version, source and provenance."""
    claim = _claim()
    link_evidence(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        text_unit_ids=("tu-src",),
    )
    add_support(
        require_knowledge(), claim_key=claim.key, document_version_id="v1",
        support=Support(
            text_unit_id=_text_unit("tu-src"),
            decision=VERIFIED,
            verification_version="jev-2026-10",
            source_ref="https://lagen.nu/1915:218#P36",
            provenance=({"kind": "text_unit", "ref": "tu-src"},),
        ),
    )
    from app.services.overgraph.catalogs import require_knowledge as catalog

    from app.services.overgraph.legal_claims import SUPPORTED_BY, evidence_key

    link = catalog().get_by_key("ClaimEvidence", evidence_key(claim.key, "v1"))
    unit = catalog().get_by_key("TextUnit", "tu-src")
    edge = catalog().get_edge_by_triple(link.engine_id, unit.engine_id, SUPPORTED_BY)
    assert edge.props["decision"] == VERIFIED
    assert edge.props["verification_version"] == "jev-2026-10"
    assert edge.props["source_ref"] == "https://lagen.nu/1915:218#P36"
    assert "tu-src" in edge.props["provenance_json"]


def test_deleting_one_document_removes_only_its_evidence_and_keeps_the_claim():
    """Three documents support one claim; deleting one leaves the claim and the other two."""
    from app.services.overgraph.legal_claims import (
        evidence_for_version,
        unlink_document_versions,
    )

    claim = _claim()
    for version in ("v1", "v2", "v3"):
        _support(claim.key, version, f"tu-{version}")
    assert unlink_document_versions(require_knowledge(), ["v2"]) == 1
    catalog = require_knowledge()
    assert [str(link.props["document_version_id"]) for link in evidence_links(catalog, claim.key)] == [
        "v3", "v1",
    ]
    assert evidence_for_version(catalog, "v2") == []
    assert claim_is_verified(catalog, claim.key, now=NOW) is True
    assert catalog.get_by_key("Claim", claim.key) is not None


def test_deleting_evidence_from_another_tenant_leaves_local_evidence_alone():
    """A purge scoped to one document version must never touch another tenant's support."""
    from app.services.knowledge.scope import customer_scope
    from app.services.overgraph.legal_claims import unlink_document_versions

    claim = _claim()
    _support(claim.key, "v1", "tu-v1")
    other_scope = customer_scope(9)
    other_claim = upsert_legal_claim(
        require_knowledge(), scope=other_scope, predicate=PREDICATE, value=VALUE,
    )
    _support(other_claim.key, "other-v1", "tu-other")
    unlink_document_versions(require_knowledge(), ["v1"])
    catalog = require_knowledge()
    assert evidence_links(catalog, claim.key) == []
    assert [str(link.props["document_version_id"]) for link in evidence_links(
        catalog, other_claim.key,
    )] == ["other-v1"]


def test_merge_folds_duplicate_claims_into_the_winner():
    """SQL cleanup merges duplicates; the graph must end up with one node and all evidence."""
    from app.services.overgraph.legal_claims import merge_claims

    catalog = require_knowledge()
    winner = _claim()
    loser = upsert_legal_claim(
        catalog, scope=SCOPE, predicate=PREDICATE, value=VALUE, key="loser-claim",
    )
    _support(winner.key, "v1", "tu-v1")
    _support(loser.key, "v2", "tu-v2")

    moved = merge_claims(catalog, winner_key=winner.key, loser_key=loser.key)
    assert moved >= 1
    assert catalog.get_by_key("Claim", "loser-claim") is None
    assert sorted(supporting_text_units(catalog, winner.key)) == ["tu-v1", "tu-v2"]
    assert sorted(
        str(link.props["document_version_id"]) for link in evidence_links(catalog, winner.key)
    ) == ["v1", "v2"]


def test_merge_keeps_answered_by_links():
    from app.services.overgraph.claim_answers import claim_answers_for_question, link_claim_answer
    from app.services.overgraph.legal_claims import merge_claims

    catalog = require_knowledge()
    winner = _claim()
    loser = upsert_legal_claim(
        catalog, scope=SCOPE, predicate=PREDICATE, value=VALUE, key="loser-answer",
    )
    link_claim_answer(
        catalog, claim_key=loser.key, scope=SCOPE, question_key="q-merge",
        research_need_id="need-1",
    )
    merge_claims(catalog, winner_key=winner.key, loser_key="loser-answer")
    keys = [str(node.key) for node in claim_answers_for_question(
        catalog, customer_id=4, question_key="q-merge",
    )]
    assert keys == [winner.key]
