"""OverGraph claim and verification-observation node model (PR step 1)."""

from pathlib import Path

from app.services.knowledge.identity import knowledge_claim_identity
from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.claims import (
    CANDIDATE_KIND,
    VERIFICATION_KIND,
    ClaimWrite,
    VerificationObservationWrite,
    claim_key,
    claim_value,
    declare_claim_indexes,
    find_claims,
    find_claims_by_class,
    upsert_claim,
    upsert_verification_observation,
)
from app.services.overgraph.labels import (
    CLAIM,
    DOCUMENT_VERSION,
    HAS_CLAIM,
    SUPPORTS,
    TEXT_UNIT,
    VERIFICATION_OBSERVATION,
    scope_label,
)

DIM = 16


def _catalog(tmp_path: Path):
    return open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)


def _seed_text_unit(catalog, *, scope, unit_id: str, document_version_id: str, document_id: str):
    catalog.upsert_node(
        [TEXT_UNIT, scope_label(scope.scope_key)],
        unit_id,
        props={
            "scope_key": scope.scope_key,
            "document_id": document_id,
            "document_version_id": document_version_id,
            "text": "Klausul om sekretess.",
            "content_hash": f"hash-{unit_id}",
            "ordinal": 0,
        },
    )
    return catalog.get_by_key(TEXT_UNIT, unit_id)


def _claim(*, scope, document_id="doc-1", document_version_id="ver-1", class_id="confidentiality_obligation", value=True, source_unit_keys=("unit-1",)):
    return ClaimWrite(
        class_id=class_id,
        document_id=document_id,
        document_version_id=document_version_id,
        value=value,
        polarity="positive",
        taxonomy_version="v1",
        scope=scope,
        source_unit_keys=source_unit_keys,
    )


def test_claim_key_matches_knowledge_identity():
    scope = shared_scope()
    value = claim_value(
        document_id="doc-1",
        document_version_id="ver-1",
        value=True,
        polarity="positive",
        taxonomy_version="v1",
    )
    assert claim_key(scope, "confidentiality_obligation", value) == knowledge_claim_identity(
        scope_key="shared", predicate="confidentiality_obligation", value=value,
    )


def test_upsert_claim_stores_props_and_edges(tmp_path):
    catalog = _catalog(tmp_path)
    scope = shared_scope()
    _seed_text_unit(catalog, scope=scope, unit_id="unit-1", document_version_id="ver-1", document_id="doc-1")

    node = upsert_claim(catalog, _claim(scope=scope))

    assert node.key == claim_key(
        scope,
        "confidentiality_obligation",
        claim_value(
            document_id="doc-1", document_version_id="ver-1", value=True,
            polarity="positive", taxonomy_version="v1",
        ),
    )
    assert node.props["class_id"] == "confidentiality_obligation"
    assert node.props["value"] is True
    assert node.props["document_version_id"] == "ver-1"

    version = catalog.get_by_key(DOCUMENT_VERSION, "ver-1")
    assert version is not None and version.engine_id is not None
    assert catalog.neighbors(
        version.engine_id, direction="outgoing", edge_label_filter=[HAS_CLAIM],
    ) == [node.engine_id]

    unit = catalog.get_by_key(TEXT_UNIT, "unit-1")
    assert unit is not None and unit.engine_id is not None
    assert catalog.neighbors(
        unit.engine_id, direction="outgoing", edge_label_filter=[SUPPORTS],
    ) == [node.engine_id]


def test_find_claims_is_scope_isolated(tmp_path):
    catalog = _catalog(tmp_path)
    shared = shared_scope()
    customer = customer_scope(7)

    upsert_claim(catalog, _claim(scope=shared))
    upsert_claim(catalog, _claim(scope=customer))

    rows, cursor = find_claims(catalog, scope=shared, class_id="confidentiality_obligation", value=True)
    assert [row.props["scope_key"] for row in rows] == ["shared"]
    assert cursor is None


def test_find_claims_exact_and_paginated(tmp_path):
    catalog = _catalog(tmp_path)
    scope = shared_scope()
    upsert_claim(catalog, _claim(scope=scope, document_version_id="ver-1"))
    upsert_claim(catalog, _claim(scope=scope, document_version_id="ver-2"))
    # A different value must not match.
    upsert_claim(catalog, _claim(scope=scope, document_version_id="ver-3", value=False))

    first, cursor = find_claims(
        catalog, scope=scope, class_id="confidentiality_obligation", value=True, limit=1,
    )
    assert len(first) == 1
    assert cursor is not None
    second, end = find_claims(
        catalog, scope=scope, class_id="confidentiality_obligation", value=True, limit=1, after=cursor,
    )
    assert len(second) == 1
    assert end is None
    versions = {first[0].props["document_version_id"], second[0].props["document_version_id"]}
    assert versions == {"ver-1", "ver-2"}


def test_find_claims_by_class_returns_all_values(tmp_path):
    catalog = _catalog(tmp_path)
    scope = shared_scope()
    upsert_claim(catalog, _claim(scope=scope, document_version_id="ver-1", value=True))
    upsert_claim(catalog, _claim(scope=scope, document_version_id="ver-2", value=False))

    rows, _ = find_claims_by_class(catalog, scope=scope, class_id="confidentiality_obligation")
    assert {row.props["value"] for row in rows} == {True, False}


def test_observation_candidate_and_verification(tmp_path):
    catalog = _catalog(tmp_path)
    scope = shared_scope()

    candidate = upsert_verification_observation(
        catalog,
        VerificationObservationWrite(
            class_id="confidentiality_obligation",
            document_id="doc-1",
            document_version_id="ver-1",
            value=True,
            polarity="positive",
            taxonomy_version="v1",
            scope=scope,
            kind=CANDIDATE_KIND,
            source_unit_keys=("unit-1",),
        ),
    )
    assert candidate.props["kind"] == CANDIDATE_KIND
    assert "decision" not in candidate.props

    verification = upsert_verification_observation(
        catalog,
        VerificationObservationWrite(
            class_id="confidentiality_obligation",
            document_id="doc-1",
            document_version_id="ver-1",
            value=True,
            polarity="positive",
            taxonomy_version="v1",
            scope=scope,
            kind=VERIFICATION_KIND,
            decision="UNSUPPORTED",
            source_unit_keys=("unit-1",),
            verification_method="jev",
            verification_version="jev-latest",
        ),
    )
    assert verification.props["kind"] == VERIFICATION_KIND
    assert verification.props["decision"] == "UNSUPPORTED"
    assert verification.props["verification_version"] == "jev-latest"

    # Candidate and verification are distinct nodes, not a claim.
    assert catalog.get_by_key(CLAIM, candidate.key) is None
    assert candidate.key != verification.key
    assert catalog.get_by_key(VERIFICATION_OBSERVATION, candidate.key) is not None


def test_declare_claim_indexes_returns_states(tmp_path):
    catalog = _catalog(tmp_path)
    upsert_claim(catalog, _claim(scope=shared_scope()))
    states = declare_claim_indexes(catalog)
    # Index build is asynchronous; the declarations must be accepted and report a state.
    assert len(states) == 2
    assert all(state in {"building", "ready", "failed"} for state in states)
