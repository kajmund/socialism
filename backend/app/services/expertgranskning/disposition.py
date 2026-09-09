"""Standing document outline for Word review prompts.

Built from the add-in's paragraph list (style + Word listString). The backend
does not parse docx. Computed numbers come from heading counters and listString;
written numbers are leading digits in the paragraph text. A mismatch is flagged
in the outline (demo contracts can show 6/7 in the UI while the body still
says 7.1/8.1).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.expertgranskning.schemas import WordDocumentParagraph

_WRITTEN_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)")
_HEADING_1 = re.compile(r"^(heading\s*1|rubrik\s*1)\b", re.IGNORECASE)
_HEADING_2 = re.compile(r"^(heading\s*2|rubrik\s*2)\b", re.IGNORECASE)
_HEADING_3 = re.compile(r"^(heading\s*3|rubrik\s*3)\b", re.IGNORECASE)

DEFAULT_BATCH_SIZE = 4


def extract_written_number(text: str) -> str:
    match = _WRITTEN_NUM.match(text or "")
    return match.group(1) if match else ""


def normalize_number(value: str) -> str:
    return value.strip().rstrip(".")


def clause_group_key(paragraph: WordDocumentParagraph) -> str:
    """Top-level clause id so 8.1 / 8.2 stay in the same batch."""
    list_string = (paragraph.list_string or "").strip()
    if list_string:
        return normalize_number(list_string).split(".", 1)[0]
    written = extract_written_number(paragraph.text)
    if written:
        return written.split(".", 1)[0]
    return f"idx:{paragraph.index}"


def batch_reviewable_paragraphs(
    paragraphs: Sequence[WordDocumentParagraph],
    *,
    size: int = DEFAULT_BATCH_SIZE,
) -> list[list[WordDocumentParagraph]]:
    """Pack ~size paragraphs without splitting a clause group.

    A single clause larger than ``size`` stays in one batch.
    """
    groups: list[list[WordDocumentParagraph]] = []
    current_key: str | None = None
    current_group: list[WordDocumentParagraph] = []
    for paragraph in paragraphs:
        key = clause_group_key(paragraph)
        if current_key is None or key != current_key:
            if current_group:
                groups.append(current_group)
            current_group = [paragraph]
            current_key = key
            continue
        current_group.append(paragraph)
    if current_group:
        groups.append(current_group)

    batches: list[list[WordDocumentParagraph]] = []
    current_batch: list[WordDocumentParagraph] = []
    current_count = 0
    current_has_numbered = False
    for group in groups:
        numbered = not clause_group_key(group[0]).startswith("idx:")
        overflow = bool(current_count) and current_count + len(group) > size
        numbered_conflict = numbered and current_has_numbered
        if overflow or numbered_conflict:
            batches.append(current_batch)
            current_batch = []
            current_count = 0
            current_has_numbered = False
        current_batch.extend(group)
        current_count += len(group)
        current_has_numbered = current_has_numbered or numbered
    if current_batch:
        batches.append(current_batch)
    return batches


def flatten_paragraphs(sections: Sequence[object]) -> list[WordDocumentParagraph]:
    out: list[WordDocumentParagraph] = []
    for section in sections:
        out.extend(section.paragraphs)
    return out


def document_text_from_sections(sections: Sequence[object]) -> str:
    parts: list[str] = []
    for section in sections:
        heading = (getattr(section, "heading", "") or "").strip()
        if heading:
            parts.append(heading)
        for paragraph in section.paragraphs:
            text = (paragraph.text or "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def format_batch_paragraphs(batch: Sequence[WordDocumentParagraph]) -> str:
    blocks: list[str] = []
    for paragraph in batch:
        extras = paragraph.style
        if paragraph.list_string.strip():
            extras = f"{extras} list={paragraph.list_string.strip()}"
        blocks.append(f"[{paragraph.index}] ({extras})\n{paragraph.text}")
    return "\n\n".join(blocks)


def build_disposition(paragraphs: Sequence[WordDocumentParagraph]) -> str:
    """Human-readable outline included in every Word-review LLM call."""
    lines: list[str] = []
    heading_1 = 0
    heading_2 = 0
    heading_3 = 0
    for paragraph in paragraphs:
        written = extract_written_number(paragraph.text)
        style = paragraph.style or ""
        list_string = (paragraph.list_string or "").strip()
        computed = ""
        if _HEADING_1.match(style):
            heading_1 += 1
            heading_2 = 0
            heading_3 = 0
            computed = str(heading_1)
        elif _HEADING_2.match(style):
            heading_2 += 1
            heading_3 = 0
            computed = f"{heading_1}.{heading_2}" if heading_1 else str(heading_2)
        elif _HEADING_3.match(style):
            heading_3 += 1
            if heading_1:
                computed = f"{heading_1}.{heading_2}.{heading_3}"
            else:
                computed = str(heading_3)
        if list_string:
            computed = normalize_number(list_string)
        mismatch = bool(
            written
            and computed
            and normalize_number(written) != normalize_number(computed)
        )
        preview = " ".join((paragraph.text or "").split())[:80]
        parts = [f"[{paragraph.index}]"]
        if style:
            parts.append(style)
        if list_string:
            parts.append(f'list="{list_string}"')
        if written:
            parts.append(f'written="{written}"')
        if computed:
            parts.append(f'computed="{computed}"')
        if preview:
            parts.append(preview)
        suffix = " MISMATCH" if mismatch else ""
        lines.append(" | ".join(parts) + suffix)
    return "Disposition:\n" + "\n".join(f"- {line}" for line in lines)
