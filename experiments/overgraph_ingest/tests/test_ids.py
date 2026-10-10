from overgraph_ingest.ids import (
    content_hash,
    document_id,
    document_version_id,
    text_unit_id,
)


def test_same_path_same_document_id() -> None:
    assert document_id("c", "a/b.pdf") == document_id("c", "a/b.pdf")


def test_new_bytes_new_version() -> None:
    first = document_version_id("doc", "hash-a")
    second = document_version_id("doc", "hash-b")
    assert first != second


def test_identical_text_same_content_hash() -> None:
    assert content_hash("Avtalet  förlängs") == content_hash("Avtalet förlängs")


def test_text_unit_id_uses_offsets() -> None:
    left = text_unit_id("ver", "structural-v1", 0, 10)
    right = text_unit_id("ver", "structural-v1", 0, 11)
    assert left != right
