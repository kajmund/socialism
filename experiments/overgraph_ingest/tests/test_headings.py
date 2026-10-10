from pathlib import Path

import pytest

from overgraph_ingest.benchmarks.corpus import write_lettered_clause_docx
from overgraph_ingest.extraction import extract_file
from overgraph_ingest.extraction.model import ExtractedBlock
from overgraph_ingest.ids import hash_file
from overgraph_ingest.segmentation.headings import (
    apply_heading_cues,
    clause_level,
    parse_clause_label,
)
from overgraph_ingest.segmentation.structural import segment_document

EXTRA_CORPUS = Path(__file__).resolve().parents[1] / "data" / "extra_corpus"
AVTAL_12 = EXTRA_CORPUS / "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx"
AVTAL_70 = EXTRA_CORPUS / "Avtal_70_Offertvillkor_orderbekraftelse.docx"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1. Parter", "1"),
        ("2.1 Avtalet gäller tills vidare.", "2.1"),
        ("1.1.1 Underleverantörer kräver godkännande.", "1.1.1"),
        ("Del A – Uppsägningsbesked på grund av arbetsbrist", "Del A"),
        ("A1. Uppsägning", "A1"),
        ("B10. Underskrifter", "B10"),
        ("Bilaga 1 – Prislista", "Bilaga 1"),
        ("Avtal 12 – Uppsägningsbesked", None),
        ("12", None),
        ("a) fel i utförandet", None),
        ("Datum: 2025-03-31", None),
    ],
)
def test_parse_clause_label(text: str, expected: str | None) -> None:
    assert parse_clause_label(text) == expected


def test_clause_level_uses_part_then_letter_number() -> None:
    assert clause_level("1") == 1
    assert clause_level("1.1") == 2
    assert clause_level("Del A") == 1
    assert clause_level("A1") == 2
    assert clause_level("B10") == 2
    assert clause_level("A1.1") == 3


def test_table_cells_are_not_promoted_to_headings() -> None:
    blocks = [
        ExtractedBlock(text="Avtal – Offert", heading_level=1, kind="heading"),
        ExtractedBlock(text="12", kind="table_cell"),
        ExtractedBlock(text="POS", kind="table_cell"),
        ExtractedBlock(text="A1. Offererad leverans", kind="paragraph"),
    ]
    apply_heading_cues(blocks, body_font_size=None)
    assert blocks[1].kind == "table_cell"
    assert blocks[1].heading_level is None
    assert blocks[2].kind == "table_cell"
    assert blocks[2].heading_level is None
    assert blocks[3].kind == "heading"
    assert blocks[3].clause_number == "A1"


def test_lettered_docx_assigns_clause_numbers(tmp_path: Path) -> None:
    path = tmp_path / "letterad.docx"
    write_lettered_clause_docx(path)
    extracted = extract_file(
        path.read_bytes(),
        path.name,
        hash_file(path),
        extraction_version="extract-v1",
    )
    segmented = segment_document(
        extracted,
        document_version_id="ver",
        segmentation_version="structural-v1",
        target_chars=80,
        max_chars=160,
    )
    clauses = [item.clause_number for item in segmented.structures if item.clause_number]
    assert clauses == ["Del A", "A1", "A2", "Del B", "B1", "B10"]
    assert all(block.kind == "table_cell" for block in extracted.blocks if block.text == "12")


@pytest.mark.skipif(not AVTAL_12.is_file(), reason="extra_corpus Avtal 12 is not present")
def test_avtal_12_detects_part_and_lettered_clauses() -> None:
    extracted = extract_file(
        AVTAL_12.read_bytes(),
        AVTAL_12.name,
        hash_file(AVTAL_12),
        extraction_version="extract-v1",
    )
    segmented = segment_document(
        extracted,
        document_version_id="ver",
        segmentation_version="structural-v1",
    )
    clauses = [item.clause_number for item in segmented.structures if item.clause_number]
    assert clauses == [
        "Del A",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "Del B",
        "B1",
        "B2",
        "B3",
        "B4",
        "B5",
        "B6",
        "B7",
        "B8",
        "B9",
        "B10",
    ]


@pytest.mark.skipif(not AVTAL_70.is_file(), reason="extra_corpus Avtal 70 is not present")
def test_avtal_70_detects_part_and_lettered_clauses() -> None:
    extracted = extract_file(
        AVTAL_70.read_bytes(),
        AVTAL_70.name,
        hash_file(AVTAL_70),
        extraction_version="extract-v1",
    )
    segmented = segment_document(
        extracted,
        document_version_id="ver",
        segmentation_version="structural-v1",
    )
    clauses = [item.clause_number for item in segmented.structures if item.clause_number]
    assert clauses == [
        "Del A",
        "A1",
        "A2",
        "Del B",
        "B1",
        "B2",
        "B3",
        "B4",
        "B5",
        "B6",
        "B7",
        "B8",
        "Del C",
    ]
    assert all(block.kind != "heading" or block.text.strip() != "12" for block in extracted.blocks)
