"""Tantivy fulltext index derived from OverGraph TextUnit nodes."""

import time
from pathlib import Path

import pytest

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import TEXT_UNIT, scope_label
from app.services.tantivy_index import (
    TextUnitIndex,
    build_from_overgraph,
    pending_updates,
    read_watermark,
    reconcile,
)

DIM = 16


@pytest.fixture
def catalog(tmp_path: Path):
    return open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)


def _seed(catalog, *, key, tenant, document_id, document_version_id, text):
    catalog.upsert_node(
        [TEXT_UNIT, scope_label(tenant)],
        key,
        props={
            "scope_key": tenant,
            "document_id": document_id,
            "document_version_id": document_version_id,
            "section_id": "",
            "content_hash": f"hash-{key}",
            "text": text,
        },
    )


def test_build_and_fulltext_search(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Avtalet innehåller sekretess.")
    _seed(catalog, key="tu-2", tenant="shared", document_id="doc-b", document_version_id="ver-b", text="Parterna ska samarbeta.")
    index = build_from_overgraph(catalog, tmp_path / "idx")

    result = index.search("sekretess", tenant_ids=("shared",))
    assert [hit.key for hit in result.hits] == ["tu-1"]
    assert result.total == 1


def test_swedish_stemmer_matches_inflected_forms(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Avtal om sekretess.")
    index = build_from_overgraph(catalog, tmp_path / "idx")
    result = index.search("avtalen", tenant_ids=("shared",))
    assert [hit.key for hit in result.hits] == ["tu-1"]


def test_case_insensitive(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    index = build_from_overgraph(catalog, tmp_path / "idx")
    result = index.search("SEKRETESS", tenant_ids=("shared",))
    assert [hit.key for hit in result.hits] == ["tu-1"]


def test_tenant_filter(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    _seed(catalog, key="tu-2", tenant="customer:7", document_id="doc-b", document_version_id="ver-b", text="Sekretess gäller.")
    index = build_from_overgraph(catalog, tmp_path / "idx")

    assert [h.key for h in index.search("sekretess", tenant_ids=("shared",)).hits] == ["tu-1"]
    both = index.search("sekretess", tenant_ids=("shared", "customer:7"))
    assert {h.key for h in both.hits} == {"tu-1", "tu-2"}


def test_document_filter(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    _seed(catalog, key="tu-2", tenant="shared", document_id="doc-b", document_version_id="ver-b", text="Sekretess gäller.")
    index = build_from_overgraph(catalog, tmp_path / "idx")

    result = index.search("sekretess", tenant_ids=("shared",), document_id="doc-a")
    assert [hit.key for hit in result.hits] == ["tu-1"]


def test_deterministic_pagination(tmp_path, catalog):
    for i in range(3):
        _seed(catalog, key=f"tu-{i}", tenant="shared", document_id="doc-a", document_version_id="ver-a", text=f"Sekretess klausul {i}.")
    index = build_from_overgraph(catalog, tmp_path / "idx")

    keys = []
    offset = 0
    while True:
        result = index.search("sekretess", tenant_ids=("shared",), limit=1, offset=offset)
        if not result.hits:
            break
        keys.append(result.hits[0].key)
        offset += 1
    assert keys == ["tu-0", "tu-1", "tu-2"]


def test_rebuild_reflects_changes(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    assert build_from_overgraph(catalog, tmp_path / "idx").search("sekretess", tenant_ids=("shared",)).total == 1

    _seed(catalog, key="tu-2", tenant="shared", document_id="doc-b", document_version_id="ver-b", text="Sekretess gäller.")
    index = build_from_overgraph(catalog, tmp_path / "idx")
    assert index.search("sekretess", tenant_ids=("shared",)).total == 2


def test_delete_keys_removes_document(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    _seed(catalog, key="tu-2", tenant="shared", document_id="doc-b", document_version_id="ver-b", text="Sekretess gäller.")
    index = build_from_overgraph(catalog, tmp_path / "idx")

    index.delete_keys(("tu-1",))
    assert [h.key for h in index.search("sekretess", tenant_ids=("shared",)).hits] == ["tu-2"]

    reopened = TextUnitIndex.open(tmp_path / "idx" / "current")
    assert [h.key for h in reopened.search("sekretess", tenant_ids=("shared",)).hits] == ["tu-2"]


def test_reconcile_indexes_units_updated_after_watermark(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    build_from_overgraph(catalog, tmp_path / "idx")
    index = TextUnitIndex.open(tmp_path / "idx" / "current")

    # Ensure the next unit's OverGraph updated_at exceeds the build watermark.
    time.sleep(0.005)
    _seed(catalog, key="tu-2", tenant="shared", document_id="doc-b", document_version_id="ver-b", text="Sekretess gäller.")

    watermark = read_watermark(tmp_path / "idx")
    assert pending_updates(catalog, watermark_ms=watermark) >= 1

    new_watermark = reconcile(catalog, index, watermark_ms=watermark)
    assert new_watermark > watermark
    result = index.search("sekretess", tenant_ids=("shared",))
    assert {hit.key for hit in result.hits} == {"tu-1", "tu-2"}


def test_reconcile_is_idempotent_no_duplicate_documents(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    build_from_overgraph(catalog, tmp_path / "idx")
    index = TextUnitIndex.open(tmp_path / "idx" / "current")
    watermark = read_watermark(tmp_path / "idx")

    # Re-running over the same window must not duplicate the indexed document.
    reconcile(catalog, index, watermark_ms=watermark)
    reconcile(catalog, index, watermark_ms=watermark)
    result = index.search("sekretess", tenant_ids=("shared",))
    assert result.total == 1
    assert [hit.key for hit in result.hits] == ["tu-1"]


def test_pending_updates_zero_when_caught_up(tmp_path, catalog):
    _seed(catalog, key="tu-1", tenant="shared", document_id="doc-a", document_version_id="ver-a", text="Sekretess gäller.")
    build_from_overgraph(catalog, tmp_path / "idx")
    index = TextUnitIndex.open(tmp_path / "idx" / "current")

    new_watermark = reconcile(catalog, index, watermark_ms=read_watermark(tmp_path / "idx"))
    assert pending_updates(catalog, watermark_ms=new_watermark) == 0
