"""OverGraph-backed document-property persistence (authoritative path)."""

import asyncio
from pathlib import Path

import pytest

from app.services.document_properties.graph_persistence import (
    lookup_document_properties,
    persist_candidate_property,
    persist_property_verification,
    persist_supported_property,
)
from app.services.document_properties.model import (
    CANDIDATE_KIND,
    SUPPORTED,
    UNSUPPORTED,
    VERIFICATION_KIND,
    DocumentProperty,
    PropertyVerification,
)
from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.claims import (
    ClaimWrite,
    find_claims_by_class,
    find_observations,
    supporting_text_unit_ids,
    upsert_claim,
)
from app.services.overgraph.labels import TEXT_UNIT, scope_label

DIM = 16


@pytest.fixture
def catalog(tmp_path: Path):
    return open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)


def _seed_text_unit(catalog, *, unit_id: str, document_id: str, document_version_id: str):
    catalog.upsert_node(
        [TEXT_UNIT, scope_label("customer.1")],
        unit_id,
        props={
            "scope_key": "customer:1",
            "document_id": document_id,
            "document_version_id": document_version_id,
            "text": "Klausul om sekretess.",
            "content_hash": f"hash-{unit_id}",
            "ordinal": 0,
        },
    )


def _property(doc_id: str, ver_id: str, unit_id: str) -> DocumentProperty:
    return DocumentProperty(
        class_id="confidentiality_obligation",
        document_id=doc_id,
        document_version_id=ver_id,
        value=True,
        polarity="positive",
        taxonomy_version="v1",
        source_unit_keys=(unit_id,),
    )


def _verification(decision: str, unit_id: str) -> PropertyVerification:
    return PropertyVerification(
        decision=decision,
        source_unit_keys=(unit_id,),
        verification_method="jev",
        verification_version="v1",
    )


async def test_supported_property_persists_claim_and_verification(catalog):
    _seed_text_unit(catalog, unit_id="tu-a", document_id="doc-a", document_version_id="ver-a")
    prop = _property("doc-a", "ver-a", "tu-a")

    node = await persist_supported_property(
        catalog, prop, _verification(SUPPORTED, "tu-a"), customer_id=1
    )

    assert node.props["class_id"] == "confidentiality_obligation"
    assert node.props["document_version_id"] == "ver-a"
    assert node.engine_id is not None
    assert supporting_text_unit_ids(catalog, node.engine_id) == ("tu-a",)

    scope = customer_scope(1)
    claims, _ = find_claims_by_class(catalog, scope=scope, class_id="confidentiality_obligation")
    assert [row.key for row in claims] == [node.key]
    verifications, _ = find_observations(
        catalog, scope=scope, class_id="confidentiality_obligation", kind=VERIFICATION_KIND,
    )
    assert [row.props["decision"] for row in verifications] == [SUPPORTED]


async def test_unsupported_property_stays_observation_without_claim(catalog):
    _seed_text_unit(catalog, unit_id="tu-b", document_id="doc-b", document_version_id="ver-b")
    prop = _property("doc-b", "ver-b", "tu-b")

    await persist_candidate_property(catalog, prop, customer_id=1)
    await persist_property_verification(
        catalog, prop, _verification(UNSUPPORTED, "tu-b"), customer_id=1
    )

    scope = customer_scope(1)
    claims, _ = find_claims_by_class(catalog, scope=scope, class_id="confidentiality_obligation")
    assert claims == []
    candidates, _ = find_observations(
        catalog, scope=scope, class_id="confidentiality_obligation", kind=CANDIDATE_KIND,
    )
    assert len(candidates) == 1
    assert candidates[0].props["document_id"] == "doc-b"


async def test_lookup_returns_supported_and_candidates(catalog):
    _seed_text_unit(catalog, unit_id="tu-a", document_id="doc-a", document_version_id="ver-a")
    _seed_text_unit(catalog, unit_id="tu-b", document_id="doc-b", document_version_id="ver-b")
    await persist_supported_property(
        catalog, _property("doc-a", "ver-a", "tu-a"), _verification(SUPPORTED, "tu-a"), customer_id=1,
    )
    await persist_candidate_property(catalog, _property("doc-b", "ver-b", "tu-b"), customer_id=1)

    page = await lookup_document_properties(
        catalog, customer_id=1, class_id="confidentiality_obligation"
    )
    hits = page.supported.items + page.candidates.items
    by_doc = {hit.document_id: hit for hit in hits}
    assert by_doc["doc-a"].status == "supported"
    assert by_doc["doc-a"].source_unit_keys == ("tu-a",)
    assert by_doc["doc-b"].status == "candidate"
    assert by_doc["doc-b"].source_unit_keys == ("tu-b",)

    supported_only = await lookup_document_properties(
        catalog, customer_id=1, class_id="confidentiality_obligation", include_candidates=False,
    )
    assert [hit.document_id for hit in supported_only.supported.items] == ["doc-a"]


async def test_claim_is_version_scoped(catalog):
    # Same property on two document versions must not collapse into one claim.
    _seed_text_unit(catalog, unit_id="tu-1", document_id="doc-a", document_version_id="ver-1")
    _seed_text_unit(catalog, unit_id="tu-2", document_id="doc-a", document_version_id="ver-2")
    await persist_supported_property(
        catalog, _property("doc-a", "ver-1", "tu-1"), _verification(SUPPORTED, "tu-1"), customer_id=1,
    )
    await persist_supported_property(
        catalog, _property("doc-a", "ver-2", "tu-2"), _verification(SUPPORTED, "tu-2"), customer_id=1,
    )

    scope = customer_scope(1)
    claims, _ = find_claims_by_class(catalog, scope=scope, class_id="confidentiality_obligation")
    assert {row.props["document_version_id"] for row in claims} == {"ver-1", "ver-2"}
    assert len(claims) == 2


async def test_lookup_is_scope_isolated(catalog):
    _seed_text_unit(catalog, unit_id="tu-a", document_id="doc-a", document_version_id="ver-a")
    await persist_supported_property(
        catalog, _property("doc-a", "ver-a", "tu-a"), _verification(SUPPORTED, "tu-a"), customer_id=1,
    )
    # A shared-scope claim with the same property must not leak into customer lookup.
    await asyncio.to_thread(
        upsert_claim,
        catalog,
        ClaimWrite(
            class_id="confidentiality_obligation",
            document_id="doc-x",
            document_version_id="ver-x",
            value=True,
            polarity="positive",
            taxonomy_version="v1",
            scope=shared_scope(),
            source_unit_keys=(),
        ),
    )

    page = await lookup_document_properties(
        catalog, customer_id=1, class_id="confidentiality_obligation"
    )
    assert [hit.document_id for hit in page.supported.items] == ["doc-a"]
