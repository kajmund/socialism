"""Text extraction for knowledge ingest. OCR is out of scope."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from typing import Literal, Protocol

import mammoth
import pdfplumber

ExtractionStatus = Literal["ok", "empty", "unsupported", "needs_ocr", "failed"]

PLAIN_TEXT_MIME = "text/plain"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_SUPPORTED_MIMES = frozenset({PLAIN_TEXT_MIME, PDF_MIME, DOCX_MIME})


@dataclass(frozen=True)
class ExtractedBlock:
    text: str
    locator: str | None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedDocument:
    blocks: list[ExtractedBlock]
    status: ExtractionStatus = "ok"
    message: str | None = None


class TextExtractor(Protocol):
    async def extract(self, content: bytes, mime_type: str) -> ExtractedDocument: ...


def normalize_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


class DefaultTextExtractor:
    """v1: text/plain, text-based PDF, DOCX. Scanned PDFs report needs_ocr."""

    async def extract(self, content: bytes, mime_type: str) -> ExtractedDocument:
        return await asyncio.to_thread(self._extract_sync, content, mime_type)

    def _extract_sync(self, content: bytes, mime_type: str) -> ExtractedDocument:
        kind = normalize_mime_type(mime_type)
        if kind not in _SUPPORTED_MIMES:
            return ExtractedDocument(
                blocks=[],
                status="unsupported",
                message=f"Unsupported mime type: {kind or mime_type}",
            )
        if kind == PLAIN_TEXT_MIME:
            return _extract_plaintext(content)
        if kind == PDF_MIME:
            return _extract_pdf(content)
        return _extract_docx(content)


def _extract_plaintext(content: bytes) -> ExtractedDocument:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return ExtractedDocument(blocks=[], status="failed", message=str(exc))
    blocks = _plaintext_blocks(text)
    if not blocks:
        return ExtractedDocument(blocks=[], status="empty")
    return ExtractedDocument(blocks=blocks)


def _plaintext_blocks(text: str) -> list[ExtractedBlock]:
    if not text.strip():
        return []
    blocks: list[ExtractedBlock] = []
    line_no = 1
    for raw_block in re.split(r"\n\s*\n", text):
        block_text = raw_block.strip()
        line_count = raw_block.count("\n") + 1 if raw_block else 0
        # Count leading blank lines that split() dropped so locators stay 1-indexed.
        if not block_text:
            line_no += line_count + 1
            continue
        start = line_no
        end = start + block_text.count("\n")
        locator = f"line:{start}" if end == start else f"line:{start}-{end}"
        blocks.append(ExtractedBlock(text=block_text, locator=locator, metadata={}))
        line_no = end + 2
    return blocks


def _extract_pdf(content: bytes) -> ExtractedDocument:
    try:
        pages: list[str] = []
        with pdfplumber.open(BytesIO(content)) as pdf:
            if len(pdf.pages) == 0:
                return ExtractedDocument(blocks=[], status="empty")
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
    except Exception as exc:
        return ExtractedDocument(blocks=[], status="failed", message=str(exc))

    blocks = [
        ExtractedBlock(text=text.strip(), locator=f"page:{index}", metadata={"page": index})
        for index, text in enumerate(pages, start=1)
        if text.strip()
    ]
    if blocks:
        return ExtractedDocument(blocks=blocks)
    return ExtractedDocument(
        blocks=[],
        status="needs_ocr",
        message="PDF has no extractable text",
    )


def _extract_docx(content: bytes) -> ExtractedDocument:
    try:
        result = mammoth.convert_to_html(BytesIO(content))
        html = str(result.value or "")
    except Exception as exc:
        return ExtractedDocument(blocks=[], status="failed", message=str(exc))
    paragraphs = _html_blocks(html)
    blocks = [
        ExtractedBlock(text=text, locator=f"paragraph:{index}", metadata={"paragraph": index})
        for index, text in enumerate(paragraphs, start=1)
    ]
    if not blocks:
        return ExtractedDocument(blocks=[], status="empty")
    return ExtractedDocument(blocks=blocks)


class _HtmlBlockParser(HTMLParser):
    _BLOCK_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"})

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK_TAGS:
            if self._depth == 0:
                self._buf = []
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag not in self._BLOCK_TAGS or self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0:
            text = "".join(self._buf).strip()
            if text:
                self.blocks.append(text)
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._buf.append(data)


def _html_blocks(html: str) -> list[str]:
    parser = _HtmlBlockParser()
    parser.feed(html)
    parser.close()
    if parser.blocks:
        return parser.blocks
    stripped = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", stripped).strip()
    return [text] if text else []
