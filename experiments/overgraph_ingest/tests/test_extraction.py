from pathlib import Path

from overgraph_ingest.benchmarks.corpus import (
    write_header_pdf,
    write_pdf_contract,
    write_table_docx,
    write_table_pdf,
    write_two_column_pdf,
)
from overgraph_ingest.extraction import extract_file
from overgraph_ingest.graph.schema import EXTRACT_VERSION
from overgraph_ingest.ids import hash_file


def _extract(path: Path):
    return extract_file(
        path.read_bytes(),
        path.name,
        hash_file(path),
        extraction_version=EXTRACT_VERSION,
    )


def test_pdf_preserves_text_pages_and_char_offsets(tmp_path: Path) -> None:
    path = tmp_path / "avtal.pdf"
    write_pdf_contract(path, 1, pages=2)
    extracted = _extract(path)
    assert extracted.status == "ok"
    assert extracted.pages
    included = extracted.included_blocks()
    assert any("Avtalstid" in block.text or "2.1" in block.text for block in included)
    assert all(block.page is not None and block.page >= 1 for block in included)
    assert all(block.char_start is not None and block.char_end is not None for block in included)
    assert included[0].char_start == 0
    reconstructed = "\n".join(block.text for block in included)
    assert reconstructed.startswith(included[0].text)


def test_docx_headings_and_table_cells(tmp_path: Path) -> None:
    path = tmp_path / "avtal.docx"
    write_table_docx(path)
    extracted = _extract(path)
    assert extracted.status == "ok"
    texts = [block.text for block in extracted.included_blocks()]
    assert any(block.heading_level == 1 for block in extracted.blocks)
    assert "4.1 Avtalet gäller från 2026-01-01." in texts
    assert "Cellvärde A1" in texts
    assert any(block.kind == "table_cell" for block in extracted.blocks)


def test_pdf_table_cells_are_not_dropped(tmp_path: Path) -> None:
    path = tmp_path / "tabell.pdf"
    write_table_pdf(path)
    extracted = _extract(path)
    blob = "\n".join(block.text for block in extracted.included_blocks())
    assert "Cellvärde A1" in blob
    assert "Cellvärde B2" in blob


def test_two_column_reads_left_then_right(tmp_path: Path) -> None:
    path = tmp_path / "kolumner.pdf"
    write_two_column_pdf(path)
    extracted = _extract(path)
    blob = "\n".join(block.text for block in extracted.included_blocks())
    assert blob.index("VÄNSTER") < blob.index("HÖGER")


def test_repeated_header_is_excluded(tmp_path: Path) -> None:
    path = tmp_path / "header.pdf"
    write_header_pdf(path, pages=4)
    extracted = _extract(path)
    headers = [
        block
        for block in extracted.blocks
        if block.exclude_reason == "header"
    ]
    assert headers
    assert all("KONFIDENTIELLT" in block.text for block in headers)
    included = "\n".join(block.text for block in extracted.included_blocks())
    assert "KONFIDENTIELLT" not in included
    assert "Klausul" in included
