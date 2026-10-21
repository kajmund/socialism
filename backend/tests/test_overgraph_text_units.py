"""Domain TextUnit → OverGraph write mapping (TextUnit cutover write side)."""

from pathlib import Path

from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import CONTAINS, DOCUMENT_VERSION, TEXT_UNIT
from app.services.overgraph.text_units import load_domain_text_units, upsert_text_units

DIM = 16


def test_upsert_text_units_writes_node_anchor_edge_and_vector(tmp_path: Path):
    catalog = open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)
    scope = customer_scope(1)
    unit = TextUnit(
        id="tu-1",
        document_version_id="ver-1",
        document_id="doc-1",
        section_id="sec-1",
        ordinal=0,
        text="Klausul om sekretess.",
        content_hash=hash_text("Klausul om sekretess."),
    )
    vector = [1.0] + [0.0] * (DIM - 1)

    engine_ids = upsert_text_units(catalog, [unit], scope=scope, embeddings=[vector])
    assert engine_ids == [catalog.get_by_key(TEXT_UNIT, "tu-1").engine_id]

    node = catalog.get_by_key(TEXT_UNIT, "tu-1")
    assert node is not None
    assert node.props["text"] == "Klausul om sekretess."
    assert node.props["document_id"] == "doc-1"
    assert node.dense_vector == tuple(vector)

    version = catalog.get_by_key(DOCUMENT_VERSION, "ver-1")
    assert version is not None
    assert catalog.neighbors(
        version.engine_id, direction="outgoing", edge_label_filter=[CONTAINS],
    ) == [node.engine_id]


def test_upsert_text_units_rejects_embedding_count_mismatch(tmp_path: Path):
    catalog = open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)
    unit = TextUnit(
        id="tu-1",
        document_version_id="ver-1",
        document_id="doc-1",
        section_id=None,
        ordinal=0,
        text="Klausul.",
        content_hash=hash_text("Klausul."),
    )
    try:
        upsert_text_units(catalog, [unit], scope=customer_scope(1), embeddings=[])
    except ValueError as exc:
        assert "embedding count" in str(exc)
    else:
        raise AssertionError("expected ValueError for embedding count mismatch")


def test_domain_text_unit_round_trip(tmp_path: Path):
    catalog = open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)
    scope = customer_scope(1)
    unit = TextUnit(
        id="tu-1",
        document_version_id="ver-1",
        document_id="doc-1",
        section_id="sec-1",
        ordinal=3,
        text="Klausul om sekretess.",
        content_hash=hash_text("Klausul om sekretess."),
        locator="page:2",
        page_start=2,
        page_end=2,
        char_start=10,
        char_end=40,
        metadata={"kind": "clause", "lang": "sv"},
    )
    upsert_text_units(catalog, [unit], scope=scope, section_titles={"sec-1": "Sekretess"})

    loaded = load_domain_text_units(catalog, document_version_id="ver-1")
    assert len(loaded) == 1
    got = loaded[0]
    assert got.id == "tu-1"
    assert got.document_version_id == "ver-1"
    assert got.document_id == "doc-1"
    assert got.section_id == "sec-1"
    assert got.ordinal == 3
    assert got.text == "Klausul om sekretess."
    assert got.content_hash == unit.content_hash
    assert got.locator == "page:2"
    assert got.page_start == 2
    assert got.page_end == 2
    assert got.char_start == 10
    assert got.char_end == 40
    assert got.metadata == {"kind": "clause", "lang": "sv"}
