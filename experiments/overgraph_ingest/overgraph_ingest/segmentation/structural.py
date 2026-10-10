"""Structure first, then size. Oversized clauses stay under the same structure."""

from __future__ import annotations

from dataclasses import dataclass, field

from overgraph_ingest.extraction.model import ExtractedBlock, ExtractedDocument
from overgraph_ingest.ids import (
    content_hash,
    normalize_text,
    structure_id,
    text_unit_id,
)
from overgraph_ingest.segmentation.headings import apply_heading_cues
from overgraph_ingest.segmentation.splitting import covering_ranges

DEFAULT_TARGET_CHARS = 1200
DEFAULT_MAX_CHARS = 2400


@dataclass
class StructureDraft:
    structure_id: str
    path: str
    title: str
    level: int
    parent_id: str | None
    ordinal: int
    clause_number: str | None
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int


@dataclass
class TextUnitDraft:
    text_unit_id: str
    structure_id: str
    text: str
    normalized_text: str
    content_hash: str
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    sequence: int
    bbox_json: str | None = None


@dataclass
class SegmentedDocument:
    canonical_text: str
    structures: list[StructureDraft] = field(default_factory=list)
    units: list[TextUnitDraft] = field(default_factory=list)


def segment_document(
    extracted: ExtractedDocument,
    *,
    document_version_id: str,
    segmentation_version: str,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> SegmentedDocument:
    included = extracted.included_blocks()
    apply_heading_cues(included, body_font_size=None)
    groups = _structure_groups(included)
    structures: list[StructureDraft] = []
    units: list[TextUnitDraft] = []
    open_levels: list[tuple[int, StructureDraft]] = []
    sequence = 0
    for ordinal, group in enumerate(groups):
        heading = group[0]
        level = heading.heading_level or 1
        title = heading.text.strip().splitlines()[0]
        parent = _parent_for_level(open_levels, level)
        parent_path = parent.path if parent is not None else ""
        path = f"{parent_path}/{ordinal}:{title}"
        pages = [block.page for block in group if block.page is not None]
        char_start = group[0].char_start
        char_end = group[-1].char_end
        if char_start is None or char_end is None:
            raise ValueError("included blocks must have canonical offsets")
        draft = StructureDraft(
            structure_id=structure_id(document_version_id, path),
            path=path,
            title=title,
            level=level,
            parent_id=parent.structure_id if parent is not None else None,
            ordinal=ordinal,
            clause_number=heading.clause_number,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            char_start=char_start,
            char_end=char_end,
        )
        structures.append(draft)
        open_levels = [item for item in open_levels if item[0] < level]
        open_levels.append((level, draft))
        piece_units, sequence = _units_for_group(
            group,
            structure=draft,
            document_version_id=document_version_id,
            segmentation_version=segmentation_version,
            target_chars=target_chars,
            max_chars=max_chars,
            sequence=sequence,
            trailing_newline=ordinal < len(groups) - 1,
        )
        units.extend(piece_units)
    return SegmentedDocument(
        canonical_text=_canonical_text(extracted),
        structures=structures,
        units=units,
    )


def _structure_groups(blocks: list[ExtractedBlock]) -> list[list[ExtractedBlock]]:
    if not blocks:
        return []
    groups: list[list[ExtractedBlock]] = []
    current: list[ExtractedBlock] = []
    for block in blocks:
        starts_section = block.heading_level is not None
        if starts_section and current:
            groups.append(current)
            current = [block]
            continue
        current.append(block)
    if current:
        groups.append(current)
    if groups and groups[0][0].heading_level is None:
        groups[0][0].heading_level = 1
        groups[0][0].kind = "heading"
    return groups


def _parent_for_level(
    open_levels: list[tuple[int, StructureDraft]],
    level: int,
) -> StructureDraft | None:
    for open_level, structure in reversed(open_levels):
        if open_level < level:
            return structure
    return None


def _units_for_group(
    group: list[ExtractedBlock],
    *,
    structure: StructureDraft,
    document_version_id: str,
    segmentation_version: str,
    target_chars: int,
    max_chars: int,
    sequence: int,
    trailing_newline: bool,
) -> tuple[list[TextUnitDraft], int]:
    text = _group_text(group, trailing_newline=trailing_newline)
    origin = group[0].char_start
    if origin is None:
        raise ValueError("group is missing char_start")
    ranges = covering_ranges(text, target_chars, max_chars)
    units: list[TextUnitDraft] = []
    for start, end in ranges:
        piece = text[start:end]
        abs_start = origin + start
        abs_end = origin + end
        pages = _pages_for_range(group, abs_start, abs_end)
        units.append(
            TextUnitDraft(
                text_unit_id=text_unit_id(
                    document_version_id,
                    segmentation_version,
                    abs_start,
                    abs_end,
                ),
                structure_id=structure.structure_id,
                text=piece,
                normalized_text=normalize_text(piece),
                content_hash=content_hash(piece),
                page_start=pages[0],
                page_end=pages[1],
                char_start=abs_start,
                char_end=abs_end,
                sequence=sequence,
            )
        )
        sequence += 1
    return units, sequence


def _group_text(group: list[ExtractedBlock], *, trailing_newline: bool) -> str:
    parts: list[str] = []
    for index, block in enumerate(group):
        if index:
            parts.append("\n")
        parts.append(block.text)
    if trailing_newline:
        parts.append("\n")
    return "".join(parts)


def _canonical_text(extracted: ExtractedDocument) -> str:
    parts: list[str] = []
    for index, block in enumerate(extracted.included_blocks()):
        if index:
            parts.append("\n")
        parts.append(block.text)
    return "".join(parts)


def _pages_for_range(
    group: list[ExtractedBlock],
    char_start: int,
    char_end: int,
) -> tuple[int | None, int | None]:
    pages = [
        block.page
        for block in group
        if block.page is not None
        and block.char_start is not None
        and block.char_end is not None
        and block.char_start < char_end
        and block.char_end > char_start
    ]
    if not pages:
        return None, None
    return min(pages), max(pages)


# Re-export for extractors that stamp cues after layout analysis.
__all__ = [
    "SegmentedDocument",
    "StructureDraft",
    "TextUnitDraft",
    "apply_heading_cues",
    "segment_document",
]
