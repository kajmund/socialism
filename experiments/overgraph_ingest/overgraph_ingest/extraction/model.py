"""Extracted document representation. Positions keep page and char models apart."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class ExtractedBlock:
    text: str
    page: int | None = None
    bbox: BBox | None = None
    kind: str = "paragraph"
    heading_level: int | None = None
    clause_number: str | None = None
    excluded: bool = False
    exclude_reason: str | None = None
    font_size: float | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True)
class ExtractedPage:
    number: int
    width: float
    height: float
    status: str = "ok"


@dataclass
class ExtractedDocument:
    relative_path: str
    mime_type: str
    source_hash: str
    extraction_version: str
    status: str
    error: str | None = None
    pages: list[ExtractedPage] = field(default_factory=list)
    blocks: list[ExtractedBlock] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def included_blocks(self) -> list[ExtractedBlock]:
        return [block for block in self.blocks if not block.excluded]

    def exclusions(self) -> list[ExtractedBlock]:
        return [block for block in self.blocks if block.excluded]


def assign_canonical_offsets(document: ExtractedDocument) -> str:
    """Build canonical text from included blocks and stamp char ranges."""
    parts: list[str] = []
    cursor = 0
    first = True
    for block in document.included_blocks():
        if not first:
            parts.append("\n")
            cursor += 1
        first = False
        block.char_start = cursor
        parts.append(block.text)
        cursor += len(block.text)
        block.char_end = cursor
    return "".join(parts)


def failed_document(
    relative_path: str,
    mime_type: str,
    source_hash: str,
    extraction_version: str,
    error: str,
    status: str = "failed",
) -> ExtractedDocument:
    return ExtractedDocument(
        relative_path=relative_path,
        mime_type=mime_type,
        source_hash=source_hash,
        extraction_version=extraction_version,
        status=status,
        error=error,
    )


def document_to_dict(document: ExtractedDocument) -> dict[str, Any]:
    return asdict(document)


def document_from_dict(payload: dict[str, Any]) -> ExtractedDocument:
    pages = [
        ExtractedPage(
            number=int(page["number"]),
            width=float(page["width"]),
            height=float(page["height"]),
            status=str(page.get("status") or "ok"),
        )
        for page in payload.get("pages") or []
    ]
    blocks = []
    for raw in payload.get("blocks") or []:
        bbox_raw = raw.get("bbox")
        bbox = None
        if bbox_raw is not None:
            bbox = BBox(
                x0=float(bbox_raw["x0"]),
                y0=float(bbox_raw["y0"]),
                x1=float(bbox_raw["x1"]),
                y1=float(bbox_raw["y1"]),
            )
        blocks.append(
            ExtractedBlock(
                text=str(raw["text"]),
                page=raw.get("page"),
                bbox=bbox,
                kind=str(raw.get("kind") or "paragraph"),
                heading_level=raw.get("heading_level"),
                clause_number=raw.get("clause_number"),
                excluded=bool(raw.get("excluded")),
                exclude_reason=raw.get("exclude_reason"),
                font_size=raw.get("font_size"),
                char_start=raw.get("char_start"),
                char_end=raw.get("char_end"),
            )
        )
    return ExtractedDocument(
        relative_path=str(payload["relative_path"]),
        mime_type=str(payload["mime_type"]),
        source_hash=str(payload["source_hash"]),
        extraction_version=str(payload["extraction_version"]),
        status=str(payload["status"]),
        error=payload.get("error"),
        pages=pages,
        blocks=blocks,
        metadata={str(key): str(value) for key, value in (payload.get("metadata") or {}).items()},
    )
