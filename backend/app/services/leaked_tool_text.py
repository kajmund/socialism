"""Recover tool calls the model wrote into the visible reply."""

from __future__ import annotations

import json
import re
from typing import Any

_READ_RE = re.compile(r"\b(läser|läsa|genomläser|går igenom|tittar igenom)\b", re.IGNORECASE)
_RETURN_RE = re.compile(r"\b(återkommer|kommer tillbaka)\b", re.IGNORECASE)
_PAGE_RE = re.compile(r"\bsid(?:a|an)\s+(\d+)\b", re.IGNORECASE)

_WAKE = "[[underlag]]"
_CALL_KEYS = frozenset({"tool", "name", "arguments", "parameters"})


def wake_tool_calls(text: str) -> list[tuple[int, int, str, dict[str, Any]]]:
    """Spans of [[underlag]] followed by a {tool, arguments} object."""
    decoder = json.JSONDecoder()
    found: list[tuple[int, int, str, dict[str, Any]]] = []
    start = 0
    lowered = text.lower()
    needle = _WAKE.lower()
    while True:
        at = lowered.find(needle, start)
        if at < 0:
            break
        cursor = at + len(_WAKE)
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != "{":
            start = at + len(needle)
            continue
        try:
            parsed, end = decoder.raw_decode(text, cursor)
        except json.JSONDecodeError:
            start = cursor
            continue
        call = _call_from_object(parsed)
        if call is None:
            start = end
            continue
        name, args = call
        found.append((at, end, name, args))
        start = end
    return found


def strip_wake_tool_text(text: str) -> str:
    spans = wake_tool_calls(text)
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end, _name, _args in spans:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts).strip()


def read_promise_arguments(text: str, state: dict | None) -> dict[str, Any] | None:
    """A sentence that promises to read and come back, without a tool call."""
    if not isinstance(state, dict) or not _READ_RE.search(text) or not _RETURN_RE.search(text):
        return None
    page = _page_number(text)
    source_id, tab_page = _promise_source(state, page)
    if source_id is None:
        return None
    chosen = page if page is not None else tab_page
    arguments: dict[str, Any] = {"source_id": source_id}
    if chosen is not None:
        arguments["page"] = chosen
    return arguments


def _page_number(text: str) -> int | None:
    match = _PAGE_RE.search(text)
    return int(match.group(1)) if match else None


def _promise_source(state: dict, page: int | None) -> tuple[str | None, int | None]:
    docs = [
        row for row in state.get("documents") or []
        if isinstance(row, dict) and row.get("source_id")
    ]
    if page is not None:
        matched = [row for row in docs if row.get("page") == page]
        if len(matched) == 1:
            return str(matched[0]["source_id"]), page
    if len(docs) == 1:
        tab_page = docs[0].get("page")
        return str(docs[0]["source_id"]), tab_page if isinstance(tab_page, int) else None
    mentions = [
        row.get("source_object_id")
        for row in state.get("document_mentions") or []
        if isinstance(row, dict) and row.get("source_object_id")
    ]
    if len(set(mentions)) == 1:
        return str(mentions[0]), page
    selection = state.get("selection")
    if isinstance(selection, dict) and selection.get("source_id"):
        return str(selection["source_id"]), page
    return None, None


def _call_from_object(parsed: object) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(parsed, dict) or not set(parsed) <= _CALL_KEYS:
        return None
    name = str(parsed.get("tool") or parsed.get("name") or "").strip()
    raw = parsed.get("arguments") if "arguments" in parsed else parsed.get("parameters")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not name or not isinstance(raw, dict):
        return None
    if not any(str(value).strip() for value in raw.values()):
        return None
    return name, raw
