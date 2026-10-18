"""A reply that says a passage is marked has to call focus_anchor in that turn."""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_MARKED_CLAIM = re.compile(
    r"(?:"
    r"\bnu\s+(?:är|ligger)\b(?:(?!\binte\b).){0,48}\bmarker(?:ad|ade|at)\b"
    r"|\b(?:jag|vi)\s+har\b(?:(?!\binte\b).){0,48}\bmarker(?:ad|ade|at)\b"
    r"|\bmarker(?:ad|ade|at)\b(?:(?!\binte\b).){0,48}\bi\s+vyn\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_MARK_NOTICE = json.dumps(
    {
        "marks_missing": True,
        "say": (
            "Anropa focus_anchor en gång för varje passage du säger är markerad. "
            "Säg inte att en passage är markerad förrän det anropet finns i den här turen."
        ),
    },
    ensure_ascii=False,
)


def claims_marked_passages(text: str) -> bool:
    """The reply says passages are already marked, not that they could be."""
    return _MARKED_CLAIM.search(text) is not None


def mark_followup_needed(text: str, call_names: Sequence[str], specs: Sequence[object]) -> bool:
    """A finished reply claimed marks that this turn never asked the view to paint."""
    if "focus_anchor" not in _spec_names(specs) or "focus_anchor" in call_names:
        return False
    return claims_marked_passages(text)


def missing_passage_mark_notice(
    text: str,
    messages: Sequence[Mapping[str, Any]],
    specs: Sequence[object],
) -> dict[str, Any] | None:
    if not mark_followup_needed(text, _focus_names_in(messages), specs):
        return None
    if _mark_notice_seen(messages):
        return None
    return {"role": "user", "content": _MARK_NOTICE}


def latest_assistant_text(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return _text_content(message.get("content"))
    return ""


def _spec_names(specs: Sequence[object]) -> set[str]:
    names: set[str] = set()
    for spec in specs:
        function = spec.get("function") if isinstance(spec, dict) else None
        name = function.get("name") if isinstance(function, dict) else ""
        if name:
            names.add(str(name))
    return names


def _focus_names_in(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if message.get("role") == "tool" and message.get("name") == "focus_anchor":
            names.append("focus_anchor")
        names.extend(_assistant_focus_names(message))
    return names


def _assistant_focus_names(message: Mapping[str, Any]) -> list[str]:
    if message.get("role") != "assistant":
        return []
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return []
    found: list[str] = []
    for call in raw:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        name = function.get("name") if isinstance(function, dict) else ""
        if name == "focus_anchor":
            found.append("focus_anchor")
    return found


def _mark_notice_seen(messages: Sequence[Mapping[str, Any]]) -> bool:
    needle = '"marks_missing": true'
    return any(
        message.get("role") == "user" and needle in str(message.get("content") or "")
        for message in messages
    )


def _text_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [
        str(item.get("text") or "").strip()
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part)
