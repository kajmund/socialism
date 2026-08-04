"""Sanitize LLM slot output for HTML report templates."""

from __future__ import annotations

import re
from typing import Final

_DANGEROUS_BLOCK: Final[re.Pattern[str]] = re.compile(
    r"(?is)<\s*(script|iframe|object|embed|form|link|meta|base|svg)\b[^>]*>.*?</\s*\1\s*>"
)
_DANGEROUS_VOID: Final[re.Pattern[str]] = re.compile(
    r"(?is)<\s*(script|iframe|object|embed|form|link|meta|base|svg)\b[^>]*/?\s*>"
)
_EVENT_HANDLER_ATTR: Final[re.Pattern[str]] = re.compile(
    r"(?i)\s+on[a-z]+\s*=\s*(['\"]).*?\1"
)
_EVENT_HANDLER_ATTR_UNQUOTED: Final[re.Pattern[str]] = re.compile(
    r"(?i)\s+on[a-z]+\s*=\s*[^\s>]+"
)
_JS_URI: Final[re.Pattern[str]] = re.compile(r"(?i)javascript\s*:")

_LABEL_SLOTS: Final[frozenset[str]] = frozenset(
    {
        "cover_box1_lbl",
        "cover_box2_lbl",
        "cover_box3_lbl",
    }
)

_LABEL_MAX_CHARS: Final[int] = 48

_FENCE_OPEN: Final[re.Pattern[str]] = re.compile(r"^```[a-zA-Z0-9_-]*\s*$")

_CHATTER_START: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"^(nu har jag|låt mig|här är|sammanfattningsvis|"
        r"now i have|let me|here is|here's|i'll |i will |"
        r"based on the data|having reviewed|i now have)\b",
        re.IGNORECASE,
    ),
)

_FC_CLASS: Final[re.Pattern[str]] = re.compile(
    r'\bclass=(["\']?)fc-(neu|cau|pos|neg)\1'
)
_NAKED_CLASS: Final[re.Pattern[str]] = re.compile(
    r"\bclass=([A-Za-z][\w-]*)\b(?![\"'])"
)
_MSTEP_BARE_ATTR: Final[re.Pattern[str]] = re.compile(
    r'<div\s+class="mstep"\s+mstep-num="(\d+)"\s*>',
    re.IGNORECASE,
)


def strip_all_code_fences(text: str) -> str:
    s = text.strip()
    while s.startswith("```"):
        lines = s.split("\n")
        if not lines or not lines[0].startswith("```"):
            break
        inner = lines[1:]
        out_lines: list[str] = []
        closed = False
        for line in inner:
            if line.strip() == "```":
                closed = True
                break
            out_lines.append(line)
        s = "\n".join(out_lines).strip()
        if not closed:
            break
    return s


def _line_is_chatter(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    return any(p.search(t) for p in _CHATTER_START)


def _drop_leading_lines(lines: list[str], *, is_html: bool) -> list[str]:
    # HTML-slot with no tags: keep prose/markdown (convert later) instead of stripping all.
    if is_html and not any(line.strip().startswith("<") for line in lines):
        out = list(lines)
        while out and (not out[0].strip() or _line_is_chatter(out[0])):
            out.pop(0)
        return out

    out = list(lines)
    while out:
        t = out[0].strip()
        if not t:
            out.pop(0)
            continue
        if is_html:
            if _FENCE_OPEN.match(t) or t == "```":
                out.pop(0)
                continue
            if t.startswith("<"):
                break
            if _line_is_chatter(out[0]):
                out.pop(0)
                continue
            out.pop(0)
            continue
        if _line_is_chatter(out[0]):
            out.pop(0)
            continue
        break
    return out


def _trim_trailing_chatter(lines: list[str], *, is_html: bool) -> list[str]:
    out = list(lines)
    while out:
        if not out[-1].strip():
            out.pop()
            continue
        if out[-1].strip() == "```":
            out.pop()
            continue
        if is_html and (_FENCE_OPEN.match(out[-1].strip()) or out[-1].strip() == "```"):
            out.pop()
            continue
        if _line_is_chatter(out[-1]):
            out.pop()
            continue
        break
    return out


def trim_leading_to_first_html_tag(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("<"):
            return "\n".join(lines[i:]).strip()
    return text


def inline_markdown_bold_to_html(text: str) -> str:
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)


def strip_markdown_bold(text: str) -> str:
    """Remove ** markers but keep the inner text (for titles / plain attributes)."""
    return re.sub(r"\*\*([^*]+)\*\*", r"\1", text)


def _trim_label(text: str) -> str:
    s = " ".join(text.split())
    if len(s) <= _LABEL_MAX_CHARS:
        return s
    cut = s[:_LABEL_MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return cut or s[:_LABEL_MAX_CHARS]


def _fix_html_classes(text: str) -> str:
    s = _FC_CLASS.sub(r'class="fc \2"', text)
    s = _MSTEP_BARE_ATTR.sub(
        r'<div class="mstep"><div class="mstep-num">\1</div>',
        s,
    )
    s = _NAKED_CLASS.sub(r'class="\1"', s)
    return s


def strip_dangerous_html(text: str) -> str:
    """Best-effort removal of high-risk tags/handlers from trusted-shape HTML slots."""
    s = _DANGEROUS_BLOCK.sub("", text)
    s = _DANGEROUS_VOID.sub("", s)
    s = _EVENT_HANDLER_ATTR.sub("", s)
    s = _EVENT_HANDLER_ATTR_UNQUOTED.sub("", s)
    s = _JS_URI.sub("", s)
    return s


def sanitize_slot_output(slot: str, raw: str) -> str:
    s = strip_all_code_fences(raw).strip()
    if not s:
        return ""
    is_html = slot.endswith("_html")
    lines = s.split("\n")
    lines = _drop_leading_lines(lines, is_html=is_html)
    lines = _trim_trailing_chatter(lines, is_html=is_html)
    s = "\n".join(lines).strip()
    if is_html and "<" in s:
        s = trim_leading_to_first_html_tag(s)
    if is_html:
        s = inline_markdown_bold_to_html(s)
        s = strip_dangerous_html(s)
        s = _fix_html_classes(s)
    else:
        # Text slots are HTML-escaped at render time — never inject tags here.
        s = strip_markdown_bold(s)
    if slot in _LABEL_SLOTS:
        s = _trim_label(s)
    return s.strip()
