"""Owner-backed legal claim/evidence vertical."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.legal_claims import (
    SUPPORTED_BY, VERIFIED, claim_in_graph,
    evidence_links as direct_links, legal_claim_key, supporting_text_units as direct_units,
)
from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.overgraph.owner_legal import (
    claim_is_verified, claim_record, evidence_links, find_claim_key,
    is_superseded, mark_superseded, persist_claim, supporting_text_units,
    unlink_document_versions,
)

DIMENSION = 4
SCOPE = customer_scope(1)
VALUE = {"value": False}
PREDICATE = "outcome.granted"


def _unit(key: str, version: str, text: str) -> dict:
    return {
        "labels": ["TextUnit", "scope.customer.1"], "key": key,
        "props": {
            "scope_key": "customer:1", "document_id": f"doc-{version}",
            "document_version_id": version, "content_hash": f"h-{key}",
            "text": text, "section_id": "s1", "ordinal": 0,
        },
    }


async def _setup():
    root = Path(tempfile.mkdtemp(prefix="owner-legal-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
    owner = OvergraphOwner(root / "catalog", dimension=DIMENSION,
                           socket_path=root / "owner.sock", catalog=catalog)
    await owner.start()
    first = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    second = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    await first.mutate("seed-units", {"upsert_nodes": [
        _unit("tu-a", "ver-a", "The court held that the clause was adjusted."),
        _unit("tu-b", "ver-b", "Another chamber reached the same result."),
    ]}, kind="batch")
    return owner, first, second, root


async def test_claim_write_is_visible_to_a_second_client_and_read_parity():
    owner, first, second, _root = await _setup()
    try:
        key = await persist_claim(
            first, scope=SCOPE, predicate=PREDICATE, value=VALUE,
            unit_ids=("tu-a", "tu-b"),
        )
        assert key == legal_claim_key(SCOPE, PREDICATE, VALUE)
        assert (await claim_record(second, scope_key="customer:1", identity=key)) is not None
        assert await find_claim_key(
            second, scope_key="customer:1", identity_value=VALUE, predicate=PREDICATE,
        ) == key
        links = await evidence_links(second, key)
        assert sorted(row["props"]["document_version_id"] for row in links) == ["ver-a", "ver-b"]
        assert await supporting_text_units(second, key) == ["tu-a", "tu-b"]
        assert await claim_is_verified(second, key, now=datetime.now(UTC)) is False
        # Direct parity against the same authoritative catalog.
        assert claim_in_graph(owner.catalog, scope_key="customer:1", identity=key) is not None
        assert [str(link.props["document_version_id"]) for link in direct_links(owner.catalog, key)] == ["ver-b", "ver-a"]
        assert direct_units(owner.catalog, key) == ["tu-a", "tu-b"]
    finally:
        await owner.close()


async def test_duplicate_publish_does_not_duplicate_evidence():
    owner, first, second, _root = await _setup()
    try:
        key = await persist_claim(
            first, scope=SCOPE, predicate=PREDICATE, value=VALUE, unit_ids=("tu-a",),
        )
        await persist_claim(
            first, scope=SCOPE, predicate=PREDICATE, value=VALUE, unit_ids=("tu-a",),
        )
        assert len(await evidence_links(second, key)) == 1
        assert await supporting_text_units(second, key) == ["tu-a"]
    finally:
        await owner.close()


async def test_unlink_and_supersede_are_immediately_visible():
    owner, first, second, _root = await _setup()
    try:
        key = await persist_claim(
            first, scope=SCOPE, predicate=PREDICATE, value=VALUE, unit_ids=("tu-a",),
        )
        assert await unlink_document_versions(first, ["ver-a"]) == 1
        assert await evidence_links(second, key) == []
        assert await supporting_text_units(second, key) == []
        now = datetime.now(UTC)
        await mark_superseded(
            first, key, superseded_at=now, valid_to=now + timedelta(days=1),
            successor_id="successor",
        )
        assert await is_superseded(second, key) is True
        # Direct claim status must match the owner write.
        assert claim_in_graph(owner.catalog, scope_key="customer:1", identity=key).props["status"] == "superseded"
    finally:
        await owner.close()


async def test_claim_verification_uses_owner_edge_props():
    owner, first, second, _root = await _setup()
    try:
        key = await persist_claim(
            first, scope=SCOPE, predicate=PREDICATE, value=VALUE, unit_ids=("tu-a",),
        )
        from app.services.overgraph.legal_claims import evidence_key
        await first.mutate("verify-support", {"upsert_edges": [{
            "from": {"label": "ClaimEvidence", "key": evidence_key(key, "ver-a")},
            "to": {"label": "TextUnit", "key": "tu-a"},
            "label": SUPPORTED_BY,
            "props": {"decision": VERIFIED, "provenance_json": "[]"},
        }]}, kind="batch")
        assert await claim_is_verified(second, key, now=datetime.now(UTC)) is True
    finally:
        await owner.close()
