"""Structure-aware Document → Section → TextUnit segmentation.

Headings come from markup metadata or generic display cues (markdown,
numbered titles, short all-caps lines). Domain adapters may later supply
richer section types; this module must not encode a specific domain.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
from app.services.knowledge.locators import merge_locators, page_from_locator, parse_locator
from app.services.knowledge.models import KnowledgeDocument
from app.services.knowledge.splitting import split_structured
from app.services.knowledge.units import (
    CanonicalDocument,
    DocumentSection,
    DocumentVersion,
    SegmentedDocument,
    TextUnit,
    hash_text,
    make_document_version_id,
    make_section_id,
    make_text_unit_id,
)

DEFAULT_TARGET_CHARS = 1200
DEFAULT_MAX_CHARS = 2400

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+){0,4})\.?\s+\S.{0,78}$")
_ALL_CAPS_HEADING = re.compile(r"^[A-ZÅÄÖ0-9][A-ZÅÄÖ0-9 \-/]{1,60}$")


@dataclass(frozen=True)
class _Leaf:
    text: str
    locator: str | None
    heading_level: int | None
    page: int | None
    metadata: dict[str, object]


class DocumentSegmenter:
    """Identify sections first, then emit TextUnits only inside each section."""

    def __init__(
        self,
        *,
        target_chars: int = DEFAULT_TARGET_CHARS,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        if target_chars < 1:
            raise ValueError("target_chars must be >= 1")
        if max_chars < target_chars:
            raise ValueError("max_chars must be >= target_chars")
        self.target_chars = target_chars
        self.max_chars = max_chars

    def segment(
        self,
        extracted: ExtractedDocument,
        document: KnowledgeDocument,
        *,
        content_hash: str | None = None,
        source_type: str | None = None,
        canonical_uri: str | None = None,
        document_version_id: str | None = None,
    ) -> SegmentedDocument:
        digest = content_hash or hash_text(
            "\n\n".join(block.text for block in extracted.blocks)
        )
        resolved_type = source_type or document.source_type or "uploaded_file"
        resolved_uri = (
            canonical_uri
            or document.canonical_uri
            or f"{document.provider}:{document.external_id}"
        )
        canonical = CanonicalDocument(
            id=document.document_id,
            source_type=resolved_type,
            canonical_uri=resolved_uri,
            title=document.title,
            metadata={
                "provider": document.provider,
                "external_id": document.external_id,
            },
        )
        version = DocumentVersion(
            id=document_version_id or make_document_version_id(),
            document_id=document.document_id,
            content_hash=digest,
            mime_type=document.mime_type,
            version=document.version,
        )
        leaves = _leaves(extracted.blocks)
        sections, units = self._build(canonical, version, leaves)
        return SegmentedDocument(
            document=canonical,
            version=version,
            sections=tuple(sections),
            text_units=tuple(units),
        )

    def _build(
        self,
        document: CanonicalDocument,
        version: DocumentVersion,
        leaves: Sequence[_Leaf],
    ) -> tuple[list[DocumentSection], list[TextUnit]]:
        if not leaves:
            return [], []
        if not any(leaf.heading_level is not None for leaf in leaves):
            return self._from_blocks(document, version, leaves)
        return self._from_headings(document, version, leaves)

    def _from_headings(
        self,
        document: CanonicalDocument,
        version: DocumentVersion,
        leaves: Sequence[_Leaf],
    ) -> tuple[list[DocumentSection], list[TextUnit]]:
        sections: list[DocumentSection] = []
        units: list[TextUnit] = []
        open_sections: list[tuple[int, DocumentSection]] = []
        current: DocumentSection | None = None
        body: list[_Leaf] = []
        section_ordinal = 0

        def flush() -> None:
            nonlocal body
            if current is None:
                body = []
                return
            units.extend(self._units_for_section(document, version, current, body))
            body = []

        for leaf in leaves:
            if leaf.heading_level is None:
                if current is None:
                    current = self._section(
                        document,
                        version,
                        parent=None,
                        ordinal=section_ordinal,
                        section_type="preamble",
                        title=None,
                        leaves=[leaf],
                    )
                    section_ordinal += 1
                    sections.append(current)
                    open_sections = [(1, current)]
                body.append(leaf)
                continue
            flush()
            parent = _parent_for_level(open_sections, leaf.heading_level)
            current = self._section(
                document,
                version,
                parent=parent,
                ordinal=section_ordinal,
                section_type=f"heading-{leaf.heading_level}",
                title=_heading_title(leaf.text),
                leaves=[leaf],
            )
            section_ordinal += 1
            sections.append(current)
            open_sections = [
                item for item in open_sections if item[0] < leaf.heading_level
            ]
            open_sections.append((leaf.heading_level, current))
            body = [leaf]
        flush()
        return sections, units

    def _from_blocks(
        self,
        document: CanonicalDocument,
        version: DocumentVersion,
        leaves: Sequence[_Leaf],
    ) -> tuple[list[DocumentSection], list[TextUnit]]:
        groups: list[list[_Leaf]] = []
        current: list[_Leaf] = []
        current_locator: str | None = None
        for leaf in leaves:
            if current and leaf.locator != current_locator:
                groups.append(current)
                current = []
            current.append(leaf)
            current_locator = leaf.locator
        if current:
            groups.append(current)

        sections: list[DocumentSection] = []
        units: list[TextUnit] = []
        for ordinal, group in enumerate(groups):
            section = self._section(
                document,
                version,
                parent=None,
                ordinal=ordinal,
                section_type="block",
                title=None,
                leaves=group,
            )
            sections.append(section)
            units.extend(self._units_for_section(document, version, section, group))
        return sections, units

    def _section(
        self,
        document: CanonicalDocument,
        version: DocumentVersion,
        *,
        parent: DocumentSection | None,
        ordinal: int,
        section_type: str,
        title: str | None,
        leaves: Sequence[_Leaf],
    ) -> DocumentSection:
        parent_path = parent.metadata.get("path") if parent is not None else ""
        # Ordinal is part of the path so repeated titles in one version stay unique.
        path = f"{parent_path}/{ordinal}:{title or section_type}"
        pages = [leaf.page for leaf in leaves if leaf.page is not None]
        return DocumentSection(
            id=make_section_id(
                document_version_id=version.id,
                path=path,
            ),
            document_version_id=version.id,
            document_id=document.id,
            parent_section_id=parent.id if parent is not None else None,
            ordinal=ordinal,
            type=section_type,
            title=title,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            metadata={"path": path},
        )

    def _units_for_section(
        self,
        document: CanonicalDocument,
        version: DocumentVersion,
        section: DocumentSection,
        leaves: Sequence[_Leaf],
    ) -> list[TextUnit]:
        pieces = self._pack_leaves(leaves)
        units: list[TextUnit] = []
        cursor = 0
        for ordinal, (text, locator, pages) in enumerate(pieces):
            digest = hash_text(text)
            unit_id = make_text_unit_id(
                document_version_id=version.id,
                locator=locator,
                content_hash=digest,
            )
            units.append(
                TextUnit(
                    id=unit_id,
                    document_version_id=version.id,
                    document_id=document.id,
                    section_id=section.id,
                    ordinal=ordinal,
                    text=text,
                    content_hash=digest,
                    locator=locator,
                    page_start=min(pages) if pages else page_from_locator(locator),
                    page_end=max(pages) if pages else page_from_locator(locator),
                    char_start=cursor,
                    char_end=cursor + len(text),
                    embedding_id=unit_id,
                    metadata={"section_type": section.type, "section_title": section.title},
                )
            )
            cursor += len(text) + 2
        return units

    def _pack_leaves(
        self,
        leaves: Sequence[_Leaf],
    ) -> list[tuple[str, str | None, list[int]]]:
        out: list[tuple[str, str | None, list[int]]] = []
        group: list[_Leaf] = []

        def flush() -> None:
            if not group:
                return
            texts = [leaf.text.strip() for leaf in group if leaf.text.strip()]
            if texts:
                pages = [leaf.page for leaf in group if leaf.page is not None]
                out.append(
                    (
                        "\n\n".join(texts),
                        merge_locators([leaf.locator for leaf in group]),
                        pages,
                    )
                )
            group.clear()

        def grouped_len() -> int:
            texts = [leaf.text.strip() for leaf in group if leaf.text.strip()]
            if not texts:
                return 0
            return sum(len(text) for text in texts) + 2 * (len(texts) - 1)

        for leaf in leaves:
            text = leaf.text.strip()
            if not text:
                continue
            if len(text) > self.target_chars:
                flush()
                out.extend(self._split_leaf(leaf))
                continue
            if group and grouped_len() + 2 + len(text) > self.target_chars:
                flush()
            group.append(leaf)
        flush()
        return out

    def _split_leaf(self, leaf: _Leaf) -> list[tuple[str, str | None, list[int]]]:
        parts = split_structured(leaf.text.strip(), self.target_chars, self.max_chars)
        parsed = parse_locator(leaf.locator) if leaf.locator else None
        pages = [leaf.page] if leaf.page is not None else []
        if parsed is None or parsed[0] != "line":
            return [(part, leaf.locator, pages) for part in parts]
        start = parsed[1]
        pieces: list[tuple[str, str | None, list[int]]] = []
        cursor = start
        for part in parts:
            end = cursor + part.count("\n")
            locator = f"line:{cursor}" if end == cursor else f"line:{cursor}-{end}"
            pieces.append((part, locator, pages))
            cursor = end + 1
        return pieces


def expand_text_unit_context(
    unit: TextUnit,
    units: Sequence[TextUnit],
    *,
    adjacent: int = 1,
) -> list[TextUnit]:
    """Deterministic neighbours in the same section. No LLM."""
    if adjacent < 0:
        raise ValueError("adjacent must be >= 0")
    same = [item for item in units if item.section_id == unit.section_id]
    same.sort(key=lambda item: item.ordinal)
    index = next((i for i, item in enumerate(same) if item.id == unit.id), None)
    if index is None:
        return [unit]
    start = max(0, index - adjacent)
    end = min(len(same), index + adjacent + 1)
    return same[start:end]


def _leaves(blocks: Sequence[ExtractedBlock]) -> list[_Leaf]:
    out: list[_Leaf] = []
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        page = _page(block)
        heading_level = _block_heading_level(block)
        if heading_level is not None:
            out.append(
                _Leaf(
                    text=text,
                    locator=block.locator,
                    heading_level=heading_level,
                    page=page,
                    metadata=dict(block.metadata),
                )
            )
            continue
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if len(paragraphs) == 1:
            out.append(
                _Leaf(
                    text=paragraphs[0],
                    locator=block.locator,
                    heading_level=_heading_level(paragraphs[0]),
                    page=page,
                    metadata=dict(block.metadata),
                )
            )
            continue
        for paragraph in paragraphs:
            out.append(
                _Leaf(
                    text=paragraph,
                    locator=block.locator,
                    heading_level=_heading_level(paragraph),
                    page=page,
                    metadata=dict(block.metadata),
                )
            )
    return out


def _block_heading_level(block: ExtractedBlock) -> int | None:
    raw = block.metadata.get("heading_level")
    if isinstance(raw, int) and raw >= 1:
        return raw
    return _heading_level(block.text.strip())


def _heading_level(text: str) -> int | None:
    if "\n" in text:
        return None
    markdown = _MARKDOWN_HEADING.match(text)
    if markdown:
        return len(markdown.group(1))
    numbered = _NUMBERED_HEADING.match(text)
    if numbered and len(text) <= 80:
        return numbered.group(1).count(".") + 1
    if (
        len(text) <= 80
        and not text.endswith((".", "!", "?"))
        and _ALL_CAPS_HEADING.match(text)
        and any(char.isalpha() for char in text)
    ):
        return 1
    return None


def _heading_title(text: str) -> str:
    markdown = _MARKDOWN_HEADING.match(text.strip())
    if markdown:
        return markdown.group(2).strip()
    numbered = _NUMBERED_HEADING.match(text.strip())
    if numbered:
        rest = text.strip()[len(numbered.group(1)) :].lstrip(". ").strip()
        return rest or text.strip()
    return text.strip()


def _parent_for_level(
    open_sections: Sequence[tuple[int, DocumentSection]],
    level: int,
) -> DocumentSection | None:
    for item_level, section in reversed(open_sections):
        if item_level < level:
            return section
    return None


def _page(block: ExtractedBlock) -> int | None:
    raw = block.metadata.get("page")
    if isinstance(raw, int):
        return raw
    return page_from_locator(block.locator)
