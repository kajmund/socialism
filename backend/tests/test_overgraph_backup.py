"""Consistent OverGraph backup + restore verification (§6.1 gate)."""

from pathlib import Path

from app.services.knowledge.scope import shared_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.claims import (
    ClaimWrite,
    declare_claim_indexes,
    find_claims_by_class,
    upsert_claim,
)
from app.services.overgraph.labels import (
    CLAIM,
    HAS_CLAIM,
    SUPPORTS,
    TEXT_UNIT,
    scope_label,
)

DIM = 16


def _seed_text_unit_with_vector(catalog, *, key, document_id, document_version_id, vector):
    catalog.upsert_node(
        [TEXT_UNIT, scope_label("shared")],
        key,
        props={
            "scope_key": "shared",
            "document_id": document_id,
            "document_version_id": document_version_id,
            "section_id": "",
            "content_hash": f"hash-{key}",
            "text": "Sekretess gäller.",
        },
        dense_vector=vector,
    )


def test_snapshot_restores_nodes_edges_vectors_and_indexes(tmp_path: Path):
    original = open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)
    scope = shared_scope()
    vector = [1.0] + [0.0] * (DIM - 1)
    _seed_text_unit_with_vector(
        original, key="tu-1", document_id="doc-a", document_version_id="ver-a", vector=vector,
    )
    upsert_claim(
        original,
        ClaimWrite(
            class_id="confidentiality_obligation",
            document_id="doc-a",
            document_version_id="ver-a",
            value=True,
            polarity="positive",
            taxonomy_version="v1",
            scope=scope,
            source_unit_keys=("tu-1",),
        ),
    )
    declare_claim_indexes(original)

    dest = tmp_path / "backup" / "knowledge"
    original.snapshot(dest)

    restored = open_catalog(dest, kind="knowledge", dimension=DIM)
    # Integrity: WAL/manifest/segments scrub clean.
    assert restored.scrub() == 0

    # Nodes, edges, vectors and indexes survive byte-for-byte.
    assert restored.count_nodes_by_labels([TEXT_UNIT]) == original.count_nodes_by_labels([TEXT_UNIT])
    assert restored.count_nodes_by_labels([CLAIM]) == original.count_nodes_by_labels([CLAIM])
    assert restored.count_edges_by_label(HAS_CLAIM) == original.count_edges_by_label(HAS_CLAIM)
    assert restored.count_edges_by_label(SUPPORTS) == original.count_edges_by_label(SUPPORTS)

    unit = restored.get_by_key(TEXT_UNIT, "tu-1")
    assert unit is not None and unit.dense_vector == tuple(vector)

    # Exact lookup (secondary index / query) works against the restored catalog.
    claims, _ = find_claims_by_class(restored, scope=scope, class_id="confidentiality_obligation")
    assert [row.props["document_id"] for row in claims] == ["doc-a"]
