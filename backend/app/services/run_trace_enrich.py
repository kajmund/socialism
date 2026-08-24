"""Attach post/comment content to OASIS trace rows for live + catch-up feeds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.simulation.artifact.reader import OasisArtifactReader

_TRACE_INFO_KEYS = (
    "follow_id",
    "followee_id",
    "mute_id",
    "mutee_id",
    "report_id",
    "report_reason",
)


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


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def enrich_trace_rows(db_path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach post/comment content and social-action targets to trace rows."""
    if not rows:
        return []

    reader = OasisArtifactReader(db_path)
    post_ids: set[int] = set()
    comment_ids: set[int] = set()
    follow_ids: set[int] = set()
    report_ids: set[int] = set()
    report_post_ids: set[int] = set()

    for row in rows:
        info = _parse_info(row.get("info"))
        action = str(row.get("action") or "").strip().lower()
        if action == "create_post":
            post_id = _int_or_none(info.get("post_id"))
            if post_id is not None:
                post_ids.add(post_id)
        elif action == "create_comment":
            comment_id = _int_or_none(info.get("comment_id"))
            if comment_id is not None:
                comment_ids.add(comment_id)
        elif action == "follow":
            follow_id = _int_or_none(info.get("follow_id"))
            if follow_id is not None:
                follow_ids.add(follow_id)
        elif action == "report_post":
            report_id = _int_or_none(info.get("report_id"))
            if report_id is not None:
                report_ids.add(report_id)
            post_id = _int_or_none(info.get("post_id"))
            if post_id is not None:
                report_post_ids.add(post_id)

    post_contents = reader.post_contents(post_ids | report_post_ids)
    comment_contents = reader.comment_contents(comment_ids)
    comment_post_ids = reader.comment_post_ids(comment_ids)
    followee_by_follow_id = reader.followee_ids_by_follow_id(follow_ids)
    report_reasons = reader.report_reasons_by_report_id(report_ids)

    enriched: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        info = _parse_info(row.get("info"))
        action = str(row.get("action") or "").strip().lower()
        if action == "create_post":
            post_id = _int_or_none(info.get("post_id"))
            if post_id is not None:
                out["post_id"] = post_id
                out["content"] = post_contents.get(post_id, "")
        elif action == "create_comment":
            comment_id = _int_or_none(info.get("comment_id"))
            if comment_id is not None:
                out["comment_id"] = comment_id
                out["content"] = comment_contents.get(comment_id, "")
                post_id = comment_post_ids.get(comment_id)
                if post_id is not None:
                    out["post_id"] = post_id
        elif action == "follow":
            follow_id = _int_or_none(info.get("follow_id"))
            if follow_id is not None:
                out["follow_id"] = follow_id
                followee_id = followee_by_follow_id.get(follow_id)
                if followee_id is not None:
                    out["followee_id"] = followee_id
        elif action == "unfollow":
            followee_id = _int_or_none(info.get("followee_id"))
            if followee_id is not None:
                out["followee_id"] = followee_id
        elif action in {"mute", "unmute"}:
            mutee_id = _int_or_none(info.get("mutee_id"))
            if mutee_id is not None:
                out["mutee_id"] = mutee_id
        elif action == "report_post":
            post_id = _int_or_none(info.get("post_id"))
            if post_id is not None:
                out["post_id"] = post_id
                preview = post_contents.get(post_id, "")
                if preview:
                    out["post_preview"] = preview
            report_id = _int_or_none(info.get("report_id"))
            if report_id is not None:
                out["report_id"] = report_id
                reason = report_reasons.get(report_id)
                if reason:
                    out["report_reason"] = reason
        enriched.append(out)
    return enriched


def _build_activity_info(row: dict[str, Any]) -> dict[str, Any]:
    info = dict(_parse_info(row.get("info")))
    for key in _TRACE_INFO_KEYS:
        value = row.get(key)
        if value is not None:
            info[key] = value
    post_id = row.get("post_id")
    if post_id is not None and info.get("post_id") is None:
        info["post_id"] = post_id
    return info


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
        post_preview = row.get("post_preview")
        if isinstance(post_preview, str) and post_preview:
            item["post_preview"] = post_preview
        info = _build_activity_info(row)
        if info:
            item["info"] = info
        items.append(item)
    return items
