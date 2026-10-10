from pathlib import Path

import fitz
import pytest

from overgraph_ingest.benchmarks.corpus import (
    write_blank_page_pdf,
    write_header_pdf,
    write_lettered_clause_docx,
    write_pdf_contract,
)
from overgraph_ingest.extraction.model import ExtractedBlock, ExtractedDocument
from overgraph_ingest.config import IngestConfig
from overgraph_ingest.graph.builder import build_graph
from overgraph_ingest.graph.schema import DOCUMENT, STATUS_FAILED_PERMANENT, STATUS_PUBLISHED
from overgraph_ingest.graph.verifier import verify_document
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.pipeline import run_verify
from overgraph_ingest.segmentation.structural import segment_document
from tests.conftest import ingest, make_config, unit_keys


def test_empty_page_is_not_published(ingest_paths) -> None:
    write_blank_page_pdf(ingest_paths["input"] / "tom.pdf")
    report = ingest(ingest_paths)
    assert report.outcomes[0].status == STATUS_FAILED_PERMANENT
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        docs = list(writer.iter_nodes(DOCUMENT))
        assert docs[0].props["status"] == STATUS_FAILED_PERMANENT
    finally:
        db.close()


def test_corrupt_pdf_fails_while_neighbor_publishes(ingest_paths) -> None:
    write_pdf_contract(ingest_paths["input"] / "bra.pdf", 3)
    (ingest_paths["input"] / "trasig.pdf").write_bytes(b"this is not a pdf")
    report = ingest(ingest_paths)
    by_name = {item.relative_path: item for item in report.outcomes}
    assert by_name["bra.pdf"].status == STATUS_PUBLISHED
    assert by_name["trasig.pdf"].status == STATUS_FAILED_PERMANENT
    assert by_name["trasig.pdf"].error


def test_dropped_block_fails_coverage() -> None:
    extracted = ExtractedDocument(
        relative_path="x.pdf",
        mime_type="application/pdf",
        source_hash="abc",
        extraction_version="extract-v1",
        status="ok",
        blocks=[
            ExtractedBlock(text="1. Rubrik", heading_level=1, char_start=0, char_end=9),
            ExtractedBlock(text="1.1 Brödtext.", char_start=10, char_end=23),
        ],
    )
    segmented = segment_document(
        extracted,
        document_version_id="ver",
        segmentation_version="structural-v1",
        target_chars=80,
        max_chars=160,
    )
    segmented.units = segmented.units[:-1]
    draft = build_graph(
        collection_id="c",
        document_id="d",
        document_version_id="ver",
        relative_path="x.pdf",
        source_hash="abc",
        extracted=extracted,
        segmented=segmented,
        segmentation_version="structural-v1",
        status="WRITING",
    )
    result = verify_document(extracted, segmented, draft)
    assert result.ok is False
    assert result.coverage < 1.0


def test_second_run_keeps_the_same_keys(ingest_paths) -> None:
    write_pdf_contract(ingest_paths["input"] / "avtal.pdf", 4)
    first = ingest(ingest_paths)
    first_keys = unit_keys(ingest_paths["db"])
    second = ingest(ingest_paths)
    assert first.outcomes[0].status == STATUS_PUBLISHED
    assert second.outcomes[0].status == STATUS_PUBLISHED
    assert unit_keys(ingest_paths["db"]) == first_keys
    assert first.outcomes[0].document_id == second.outcomes[0].document_id
    assert first.outcomes[0].document_version_id == second.outcomes[0].document_version_id


def test_identical_clause_in_two_files_shares_content_hash(ingest_paths) -> None:
    shared = "2.2 Om uppsägning inte sker senast tre månader före avtalstidens slut förlängs avtalet."
    _write_clause_pdf(ingest_paths["input"] / "a.pdf", "Avtal A", shared)
    _write_clause_pdf(ingest_paths["input"] / "b.pdf", "Avtal B", shared)
    report = ingest(ingest_paths)
    assert {item.status for item in report.outcomes} == {STATUS_PUBLISHED}
    assert report.outcomes[0].document_id != report.outcomes[1].document_id
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        hashes = [
            node.props["content_hash"]
            for node in writer.iter_nodes("TextUnit")
            if shared[:20] in node.props["text"]
        ]
    finally:
        db.close()
    assert len(hashes) == 2
    assert hashes[0] == hashes[1]


def test_header_excluded_from_published_coverage(ingest_paths) -> None:
    write_header_pdf(ingest_paths["input"] / "huvud.pdf", pages=4)
    report = ingest(ingest_paths)
    assert report.outcomes[0].status == STATUS_PUBLISHED
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        texts = [node.props["text"] for node in writer.iter_nodes("TextUnit")]
    finally:
        db.close()
    assert texts
    assert all("KONFIDENTIELLT" not in text for text in texts)


EXTRA_DB = Path(__file__).resolve().parents[1] / "data" / "extra-overgraph"
EXTRA_CACHE = Path(__file__).resolve().parents[1] / "data" / "extra-cache"


def test_published_document_survives_close_and_reopen(ingest_paths) -> None:
    write_lettered_clause_docx(ingest_paths["input"] / "letterad.docx")
    report = ingest(ingest_paths)
    outcome = report.outcomes[0]
    assert outcome.status == STATUS_PUBLISHED
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        documents = list(writer.iter_nodes(DOCUMENT))
        assert len(documents) == 1
        assert documents[0].props["status"] == STATUS_PUBLISHED
        assert documents[0].props["document_version_id"] == outcome.document_version_id
        units = sorted(
            [
                node
                for node in writer.iter_nodes("TextUnit")
                if node.props.get("document_version_id") == outcome.document_version_id
            ],
            key=lambda node: int(node.props["sequence"]),
        )
        reconstructed = "".join(node.props["text"] for node in units)
    finally:
        db.close()
    assert len(units) == outcome.text_units
    assert len(reconstructed) == outcome.chars
    assert "A1. Uppsägning" in reconstructed
    assert "B10. Underskrifter" in reconstructed
    assert run_verify(make_config(ingest_paths)) == []


@pytest.mark.skipif(not EXTRA_DB.is_dir(), reason="extra-overgraph baseline database is not present")
def test_extra_corpus_database_survives_reopen() -> None:
    errors = run_verify(
        IngestConfig(
            db_path=EXTRA_DB,
            cache_dir=EXTRA_CACHE,
            collection_id="extra-corpus",
            dense_dimension=8,
        )
    )
    assert errors == []
    db = open_database(EXTRA_DB, 8)
    try:
        writer = GraphWriter(db, batch_size=500)
        published = [
            node
            for node in writer.iter_nodes(DOCUMENT)
            if node.props.get("status") == STATUS_PUBLISHED
        ]
    finally:
        db.close()
    assert len(published) == 100


def test_published_document_reconstructs_source_order(ingest_paths) -> None:
    write_pdf_contract(ingest_paths["input"] / "ordning.pdf", 5)
    ingest(ingest_paths)
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        units = sorted(
            writer.iter_nodes("TextUnit"),
            key=lambda node: int(node.props["sequence"]),
        )
    finally:
        db.close()
    reconstructed = "".join(node.props["text"] for node in units)
    assert "Avtalstid" in reconstructed or "2.1" in reconstructed
    assert reconstructed


def _write_clause_pdf(path: Path, title: str, clause: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"1. {title}", fontsize=14)
    page.insert_text((72, 110), clause, fontsize=11)
    doc.save(path)
    doc.close()
