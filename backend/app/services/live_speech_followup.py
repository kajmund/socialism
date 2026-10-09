"""Speak a tool follow-up that the chat already published."""

from __future__ import annotations

from typing import Any


def published_assistant_reply(
    payload: dict[str, Any],
    *,
    expert_id: str,
    assistant_text: str,
    voiced: str,
) -> str | None:
    if payload.get("thread_id") != expert_id:
        return None
    if payload.get("mode") not in (None, "character"):
        return None
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "assistant":
        return None
    text = str(last.get("content") or "").strip()
    if not text or text in {assistant_text.strip(), voiced}:
        return None
    return text
