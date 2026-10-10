"""PDF extraction with PyMuPDF: reading order, tables, headers, coordinates."""

from __future__ import annotations

import statistics
from collections import Counter
from io import BytesIO

import fitz

from overgraph_ingest.extraction.model import (
    BBox,
    ExtractedBlock,
    ExtractedDocument,
    ExtractedPage,
    assign_canonical_offsets,
    failed_document,
)
from overgraph_ingest.graph.schema import EXTRACT_VERSION
from overgraph_ingest.segmentation.headings import apply_heading_cues

HEADER_ZONE = 0.12
FOOTER_ZONE = 0.88
REPEAT_MIN_PAGES = 3


def extract_pdf(
    data: bytes,
    relative_path: str,
    source_hash: str,
    *,
    extraction_version: str = EXTRACT_VERSION,
) -> ExtractedDocument:
    try:
        pdf = fitz.open(stream=BytesIO(data), filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — corrupt PDF is an ingest outcome
        return failed_document(
            relative_path,
            "application/pdf",
            source_hash,
            extraction_version,
            str(exc),
        )
    try:
        if pdf.page_count == 0:
            return failed_document(
                relative_path,
                "application/pdf",
                source_hash,
                extraction_version,
                "PDF has no pages",
                status="empty",
            )
        pages: list[ExtractedPage] = []
        blocks: list[ExtractedBlock] = []
        for index in range(pdf.page_count):
            page = pdf[index]
            page_blocks, status = _extract_page(page, index + 1)
            pages.append(
                ExtractedPage(
                    number=index + 1,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    status=status,
                )
            )
            blocks.extend(page_blocks)
    finally:
        pdf.close()

    _mark_repeated_margins(blocks, pages)
    _infer_headings(blocks)
    document = ExtractedDocument(
        relative_path=relative_path,
        mime_type="application/pdf",
        source_hash=source_hash,
        extraction_version=extraction_version,
        status=_document_status(pages),
        error=_document_error(pages),
        pages=pages,
        blocks=blocks,
    )
    assign_canonical_offsets(document)
    return document


def _extract_page(page: fitz.Page, number: int) -> tuple[list[ExtractedBlock], str]:
    raw = page.get_text("dict")
    width = float(page.rect.width)
    height = float(page.rect.height)
    tables = _page_tables(page)
    text_blocks: list[ExtractedBlock] = []
    image_only = True
    for block in raw.get("blocks") or []:
        if int(block.get("type") or 0) != 0:
            continue
        image_only = False
        extracted = _text_block(block, number)
        if extracted is None:
            continue
        if _overlaps_table(extracted.bbox, tables):
            continue
        text_blocks.append(extracted)
    cell_blocks = _table_blocks(tables, number)
    if not text_blocks and not cell_blocks:
        return [], "needs_ocr" if image_only else "empty"
    ordered = _reading_order(text_blocks, width, height)
    return [*ordered, *cell_blocks], "ok"


def _text_block(block: dict, page: int) -> ExtractedBlock | None:
    lines = []
    sizes: list[float] = []
    for line in block.get("lines") or []:
        pieces = []
        for span in line.get("spans") or []:
            piece = str(span.get("text") or "")
            if piece:
                pieces.append(piece)
            size = span.get("size")
            if size:
                sizes.append(float(size))
        if pieces:
            lines.append("".join(pieces))
    text = "\n".join(lines)
    if not text.strip():
        return None
    bbox = _bbox(block.get("bbox"))
    return ExtractedBlock(
        text=text,
        page=page,
        bbox=bbox,
        kind="paragraph",
        font_size=max(sizes) if sizes else None,
    )


def _page_tables(page: fitz.Page) -> list[dict]:
    finder = page.find_tables()
    tables = getattr(finder, "tables", None) or []
    out: list[dict] = []
    for table in tables:
        bbox = _bbox(getattr(table, "bbox", None))
        rows = table.extract()
        cells = list(getattr(table, "cells", None) or [])
        out.append({"bbox": bbox, "rows": rows, "cells": cells})
    return out


def _table_blocks(tables: list[dict], page: int) -> list[ExtractedBlock]:
    blocks: list[ExtractedBlock] = []
    for table in tables:
        cells = table["cells"]
        index = 0
        for row in table["rows"]:
            for cell in row:
                text = (cell or "").strip()
                bbox = None
                if index < len(cells) and cells[index] is not None:
                    bbox = _bbox(cells[index])
                index += 1
                if not text:
                    continue
                blocks.append(
                    ExtractedBlock(
                        text=text,
                        page=page,
                        bbox=bbox,
                        kind="table_cell",
                    )
                )
    return blocks


def _overlaps_table(bbox: BBox | None, tables: list[dict]) -> bool:
    if bbox is None:
        return False
    for table in tables:
        other = table.get("bbox")
        if other is None:
            continue
        if bbox.x1 <= other.x0 or other.x1 <= bbox.x0:
            continue
        if bbox.y1 <= other.y0 or other.y1 <= bbox.y0:
            continue
        overlap_x = min(bbox.x1, other.x1) - max(bbox.x0, other.x0)
        overlap_y = min(bbox.y1, other.y1) - max(bbox.y0, other.y0)
        area = max(bbox.x1 - bbox.x0, 1.0) * max(bbox.y1 - bbox.y0, 1.0)
        if (overlap_x * overlap_y) / area > 0.5:
            return True
    return False


def _reading_order(
    blocks: list[ExtractedBlock],
    page_width: float,
    page_height: float,
) -> list[ExtractedBlock]:
    del page_height
    if len(blocks) < 4:
        return sorted(blocks, key=lambda block: _sort_key(block))
    split = _column_split(blocks, page_width)
    if split is None:
        return sorted(blocks, key=_sort_key)
    left, right = split
    return sorted(left, key=_sort_key) + sorted(right, key=_sort_key)


def _column_split(
    blocks: list[ExtractedBlock],
    page_width: float,
) -> tuple[list[ExtractedBlock], list[ExtractedBlock]] | None:
    best: tuple[int, list[ExtractedBlock], list[ExtractedBlock]] | None = None
    for fraction in (0.4, 0.45, 0.5, 0.55, 0.6):
        split_x = page_width * fraction
        left: list[ExtractedBlock] = []
        right: list[ExtractedBlock] = []
        crossing = 0
        for block in blocks:
            bbox = block.bbox
            if bbox is None:
                left.append(block)
                continue
            if bbox.x1 <= split_x:
                left.append(block)
            elif bbox.x0 >= split_x:
                right.append(block)
            else:
                crossing += 1
                if (bbox.x0 + bbox.x1) / 2 < split_x:
                    left.append(block)
                else:
                    right.append(block)
        if not left or not right:
            continue
        if crossing > max(1, len(blocks) // 10):
            continue
        if best is None or crossing < best[0]:
            best = (crossing, left, right)
    if best is None:
        return None
    return best[1], best[2]


def _sort_key(block: ExtractedBlock) -> tuple[float, float]:
    if block.bbox is None:
        return (0.0, 0.0)
    return (block.bbox.y0, block.bbox.x0)


def _mark_repeated_margins(
    blocks: list[ExtractedBlock],
    pages: list[ExtractedPage],
) -> None:
    if len(pages) < 2:
        return
    heights = {page.number: page.height for page in pages}
    header_pages: Counter[str] = Counter()
    footer_pages: Counter[str] = Counter()
    for block in blocks:
        if block.page is None or block.bbox is None:
            continue
        height = heights.get(block.page)
        if height is None:
            continue
        key = " ".join(block.text.split())
        if block.bbox.y0 <= height * HEADER_ZONE:
            header_pages[key] += 1
        if block.bbox.y1 >= height * FOOTER_ZONE:
            footer_pages[key] += 1
    threshold = max(REPEAT_MIN_PAGES, (len(pages) + 1) // 2)
    headers = {key for key, count in header_pages.items() if count >= threshold}
    footers = {key for key, count in footer_pages.items() if count >= threshold}
    for block in blocks:
        key = " ".join(block.text.split())
        if key in headers:
            block.excluded = True
            block.exclude_reason = "header"
        elif key in footers:
            block.excluded = True
            block.exclude_reason = "footer"


def _infer_headings(blocks: list[ExtractedBlock]) -> None:
    sizes = [block.font_size for block in blocks if block.font_size]
    body = statistics.median(sizes) if sizes else None
    apply_heading_cues(blocks, body_font_size=body)


def _document_status(pages: list[ExtractedPage]) -> str:
    if any(page.status == "needs_ocr" for page in pages):
        return "needs_ocr"
    if pages and all(page.status == "empty" for page in pages):
        return "empty"
    if any(page.status == "empty" for page in pages):
        return "needs_ocr"
    return "ok"


def _document_error(pages: list[ExtractedPage]) -> str | None:
    missing = [page.number for page in pages if page.status in {"needs_ocr", "empty"}]
    if not missing:
        return None
    joined = ", ".join(str(number) for number in missing)
    return f"pages without extractable text: {joined}"


def _bbox(raw: object) -> BBox | None:
    if raw is None:
        return None
    if isinstance(raw, BBox):
        return raw
    values = list(raw)
    if len(values) < 4:
        return None
    return BBox(
        x0=float(values[0]),
        y0=float(values[1]),
        x1=float(values[2]),
        y1=float(values[3]),
    )
