"""DOCX extraction that keeps paragraph, heading, list, and table order."""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from overgraph_ingest.extraction.model import (
    ExtractedBlock,
    ExtractedDocument,
    assign_canonical_offsets,
    failed_document,
)
from overgraph_ingest.graph.schema import EXTRACT_VERSION
from overgraph_ingest.segmentation.headings import apply_heading_cues


def extract_docx(
    data: bytes,
    relative_path: str,
    source_hash: str,
    *,
    extraction_version: str = EXTRACT_VERSION,
) -> ExtractedDocument:
    try:
        document = Document(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — malformed DOCX is an ingest outcome
        return failed_document(
            relative_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            source_hash,
            extraction_version,
            str(exc),
        )

    blocks: list[ExtractedBlock] = []
    for item in _iter_body(document):
        if isinstance(item, Paragraph):
            block = _paragraph_block(item)
            if block is not None:
                blocks.append(block)
        elif isinstance(item, Table):
            blocks.extend(_table_blocks(item))

    apply_heading_cues(blocks, body_font_size=None)
    extracted = ExtractedDocument(
        relative_path=relative_path,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        source_hash=source_hash,
        extraction_version=extraction_version,
        status="ok" if blocks else "empty",
        error=None if blocks else "DOCX has no extractable text",
        blocks=blocks,
        metadata=_core_metadata(document),
    )
    assign_canonical_offsets(extracted)
    return extracted


def _iter_body(document: Document):
    for child in document.element.body:
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _paragraph_block(paragraph: Paragraph) -> ExtractedBlock | None:
    text = paragraph.text
    if not text.strip():
        return None
    style_name = paragraph.style.name if paragraph.style is not None else ""
    heading_level = _heading_level(style_name)
    kind = "heading" if heading_level is not None else "paragraph"
    if _is_list_item(paragraph):
        kind = "list_item"
    return ExtractedBlock(
        text=text,
        kind=kind,
        heading_level=heading_level,
    )


def _table_blocks(table: Table) -> list[ExtractedBlock]:
    blocks: list[ExtractedBlock] = []
    for row in table.rows:
        for cell in row.cells:
            text = cell.text.strip()
            if not text:
                continue
            blocks.append(ExtractedBlock(text=text, kind="table_cell"))
    return blocks


def _heading_level(style_name: str) -> int | None:
    if not style_name.startswith("Heading"):
        return None
    suffix = style_name.replace("Heading", "", 1).strip()
    if not suffix:
        return 1
    try:
        return int(suffix)
    except ValueError:
        return 1


def _is_list_item(paragraph: Paragraph) -> bool:
    props = paragraph._p.pPr
    return props is not None and props.numPr is not None


def _core_metadata(document: Document) -> dict[str, str]:
    core = document.core_properties
    metadata = {}
    if core.title:
        metadata["title"] = core.title
    if core.author:
        metadata["author"] = core.author
    return metadata
