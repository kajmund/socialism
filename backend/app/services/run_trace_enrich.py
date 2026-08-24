"""Attach post/comment content to OASIS trace rows for live + catch-up feeds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.simulation.artifact.reader import OasisArtifactReader


def _parse_info(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def enrich_trace_rows(db_path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach post/comment content + post_id-for-comment to trace rows."""
    if not rows:
        return []

    reader = OasisArtifactReader(db_path)
    post_ids: set[int] = set()
    comment_ids: set[int] = set()
    for row in rows:
        info = _parse_info(row.get("info"))
        action = str(row.get("action") or "").strip().lower()
        if action == "create_post":
            post_id = info.get("post_id")
            if post_id is not None:
                post_ids.add(int(post_id))
        elif action == "create_comment":
            comment_id = info.get("comment_id")
            if comment_id is not None:
                comment_ids.add(int(comment_id))

    post_contents = reader.post_contents(post_ids)
    comment_contents = reader.comment_contents(comment_ids)
    comment_post_ids = reader.comment_post_ids(comment_ids)

    enriched: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        info = _parse_info(row.get("info"))
        action = str(row.get("action") or "").strip().lower()
        if action == "create_post":
            post_id = info.get("post_id")
            if post_id is not None:
                pid = int(post_id)
                out["post_id"] = pid
                out["content"] = post_contents.get(pid, "")
        elif action == "create_comment":
            comment_id = info.get("comment_id")
            if comment_id is not None:
                cid = int(comment_id)
                out["comment_id"] = cid
                out["content"] = comment_contents.get(cid, "")
                post_id = comment_post_ids.get(cid)
                if post_id is not None:
                    out["post_id"] = int(post_id)
        enriched.append(out)
    return enriched


def activity_items_from_trace_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten enriched trace rows into WS activity item payloads."""
    items: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {
            "user_id": int(row["user_id"]),
            "action": str(row.get("action") or ""),
            "created_at": row.get("created_at"),
        }
        post_id = row.get("post_id")
        if post_id is not None:
            item["post_id"] = int(post_id)
        comment_id = row.get("comment_id")
        if comment_id is not None:
            item["comment_id"] = int(comment_id)
        content = row.get("content")
        if isinstance(content, str) and content:
            item["content"] = content
        items.append(item)
    return items
