from pathlib import Path

from overgraph_ingest.benchmarks.corpus import write_header_pdf, write_two_column_pdf
from overgraph_ingest.config import IngestConfig
from overgraph_ingest.extraction import extract_file
from overgraph_ingest.extraction.model import ExtractedBlock, ExtractedDocument
from overgraph_ingest.graph.builder import build_graph
from overgraph_ingest.graph.verifier import reconstruct_canonical, verify_document
from overgraph_ingest.ids import hash_file
from overgraph_ingest.quality.evaluate import evaluate_gold_dir, evaluate_prepared
from overgraph_ingest.quality.gold import GoldFixture, generate_gold_set
from overgraph_ingest.segmentation.structural import segment_document


def _config(tmp_path: Path) -> IngestConfig:
    return IngestConfig(db_path=tmp_path / "db", dense_dimension=8)


def _extract_and_segment(path: Path):
    extracted = extract_file(
        path.read_bytes(),
        path.name,
        hash_file(path),
        extraction_version="extract-v1",
    )
    segmented = segment_document(
        extracted,
        document_version_id="gold",
        segmentation_version="structural-v1",
        target_chars=80,
        max_chars=160,
    )
    return extracted, segmented


def test_units_reconstruct_canonical_character_for_character(tmp_path: Path) -> None:
    path = tmp_path / "avtal.pdf"
    write_two_column_pdf(path)
    extracted, segmented = _extract_and_segment(path)
    reconstructed = reconstruct_canonical(segmented.units)
    assert reconstructed == segmented.canonical_text
    draft = build_graph(
        collection_id="c",
        document_id="d",
        document_version_id="gold",
        relative_path=path.name,
        source_hash="x",
        extracted=extracted,
        segmented=segmented,
        segmentation_version="structural-v1",
        status="WRITING",
    )
    result = verify_document(extracted, segmented, draft)
    assert result.reconstructed is True
    assert result.ok is True


def test_changed_whitespace_fails_reconstruction() -> None:
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
    segmented.units[0].text = segmented.units[0].text.replace("\n", " ")
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
    assert result.reconstructed is False
    assert result.ok is False


def test_gold_set_scores_layout_and_tables(tmp_path: Path) -> None:
    gold_dir = tmp_path / "gold"
    generate_gold_set(gold_dir)
    scores = {
        score.name: score
        for score in evaluate_gold_dir(gold_dir, _config(tmp_path), origin="synthetic")
    }
    two_column = scores["two_column_simple"]
    assert two_column.reading_order_ok is True
    table = scores["table_docx"]
    assert table.table_ok is True
    header = scores["header_footer"]
    assert header.exclusion_ok is True
    numbering = scores["complex_numbering"]
    assert numbering.clause_recall == 1.0
    assert numbering.hierarchy_ok is True


def test_header_exclusion_is_not_silent(tmp_path: Path) -> None:
    path = tmp_path / "huvud.pdf"
    write_header_pdf(path, pages=4)
    extracted, segmented = _extract_and_segment(path)
    score = evaluate_prepared(
        extracted,
        segmented,
        GoldFixture(
            name="header",
            relative_path=path.name,
            kind="exclusion",
            origin="synthetic",
            must_exclude=["KONFIDENTIELLT - Avtal 2026"],
            must_include=["Klausul"],
        ),
    )
    assert score.exclusion_ok is True
    assert score.extraction_errors == 0
