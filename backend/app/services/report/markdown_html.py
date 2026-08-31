"""Safe markdown → HTML for report bodies. No HTML passthrough."""

from __future__ import annotations

import re
from html import escape

from app.services.spindoctor_refs import strip_spindoctor_refs

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(\S.*)$")
_NUMBERED = re.compile(r"^\s*\d+\.\s+(\S.*)$")
_HR = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_INLINE = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")


def markdown_to_html(text: str) -> str:
    """Render a subset of markdown (headings, lists, bold/italic) as escaped HTML."""
    source = strip_spindoctor_refs(text.replace("\r\n", "\n")).strip()
    if not source:
        return ""

    lines = source.split("\n")
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _HR.match(line):
            blocks.append("<hr/>")
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if _BULLET.match(line):
            items: list[str] = []
            while i < len(lines):
                match = _BULLET.match(lines[i])
                if not match:
                    break
                items.append(f"<li>{_inline(match.group(1))}</li>")
                i += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue
        if _NUMBERED.match(line):
            items = []
            while i < len(lines):
                match = _NUMBERED.match(lines[i])
                if not match:
                    break
                items.append(f"<li>{_inline(match.group(1))}</li>")
                i += 1
            blocks.append(f"<ol>{''.join(items)}</ol>")
            continue
        if not line.strip():
            i += 1
            continue
        para = [line]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not _HEADING.match(lines[i])
            and not _BULLET.match(lines[i])
            and not _NUMBERED.match(lines[i])
            and not _HR.match(lines[i])
        ):
            para.append(lines[i])
            i += 1
        body = "<br/>".join(_inline(row) for row in para)
        blocks.append(f"<p>{body}</p>")
    return "".join(blocks)


def _inline(text: str) -> str:
    parts: list[str] = []
    last = 0
    for match in _INLINE.finditer(text):
        if match.start() > last:
            parts.append(escape(text[last : match.start()]))
        if match.group(1) is not None:
            parts.append(f"<strong>{escape(match.group(1))}</strong>")
        else:
            parts.append(f"<em>{escape(match.group(2))}</em>")
        last = match.end()
    if last < len(text):
        parts.append(escape(text[last:]))
    return "".join(parts)
