"""Inventory lookup API (OverGraph-backed)."""

from __future__ import annotations

from app.services.document_properties.graph_persistence import (
    persist_candidate_property,
    persist_supported_property,
)
from app.services.document_properties.model import (
    SUPPORTED,
    DocumentProperty,
    PropertyVerification,
)


def _property(doc_id: str, ver_id: str, *, value: object = True) -> DocumentProperty:
    return DocumentProperty(
        class_id="confidentiality_obligation",
        document_id=doc_id,
        document_version_id=ver_id,
        value=value,
        polarity="positive",
        taxonomy_version="v1",
        source_unit_keys=(),
    )


def _verification() -> PropertyVerification:
    return PropertyVerification(
        decision=SUPPORTED,
        source_unit_keys=(),
        verification_method="jev",
        verification_version="v1",
    )


async def test_lookup_endpoint_returns_supported_and_candidates(client, research_overgraph):
    catalog = research_overgraph
    await persist_supported_property(catalog, _property("doc-a", "ver-a"), _verification(), customer_id=1)
    await persist_candidate_property(catalog, _property("doc-b", "ver-b"), customer_id=1)

    response = await client.get(
        "/document-properties/lookup",
        params={"customer_id": 1, "class_id": "confidentiality_obligation"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [h["document_id"] for h in body["supported"]["items"]] == ["doc-a"]
    assert [h["status"] for h in body["supported"]["items"]] == ["supported"]
    assert [h["document_id"] for h in body["candidates"]["items"]] == ["doc-b"]
    assert [h["status"] for h in body["candidates"]["items"]] == ["candidate"]


async def test_lookup_endpoint_value_filter_and_include_candidates_false(client, research_overgraph):
    catalog = research_overgraph
    await persist_supported_property(catalog, _property("doc-a", "ver-a", value=True), _verification(), customer_id=1)
    await persist_supported_property(catalog, _property("doc-b", "ver-b", value=False), _verification(), customer_id=1)
    await persist_candidate_property(catalog, _property("doc-c", "ver-c"), customer_id=1)

    filtered = await client.get(
        "/document-properties/lookup",
        params={"customer_id": 1, "class_id": "confidentiality_obligation", "value": "true"},
    )
    assert [h["document_id"] for h in filtered.json()["supported"]["items"]] == ["doc-a"]

    supported_only = await client.get(
        "/document-properties/lookup",
        params={
            "customer_id": 1,
            "class_id": "confidentiality_obligation",
            "include_candidates": "false",
        },
    )
    body = supported_only.json()
    assert body["candidates"]["items"] == []


async def test_lookup_endpoint_paginates_supported_keyset(client, research_overgraph):
    catalog = research_overgraph
    for i in range(3):
        await persist_supported_property(
            catalog, _property(f"doc-{i}", f"ver-{i}"), _verification(), customer_id=1,
        )

    first = await client.get(
        "/document-properties/lookup",
        params={"customer_id": 1, "class_id": "confidentiality_obligation", "limit": 1},
    )
    body = first.json()
    assert len(body["supported"]["items"]) == 1
    assert body["supported"]["after"] is not None

    second = await client.get(
        "/document-properties/lookup",
        params={
            "customer_id": 1,
            "class_id": "confidentiality_obligation",
            "limit": 1,
            "supported_after": body["supported"]["after"],
        },
    )
    assert len(second.json()["supported"]["items"]) == 1
    first_doc = body["supported"]["items"][0]["document_id"]
    second_doc = second.json()["supported"]["items"][0]["document_id"]
    assert first_doc != second_doc
