"""Help-chat tools for creating and reading feedback items."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.domain import FeedbackItemCreate, FeedbackKind, FeedbackStatus
from app.services.feedback import (
    create_feedback_item,
    list_feedback_items,
    serialize_feedback_item,
)

FEEDBACK_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "feedback_create",
            "description": (
                "Save a bug report, product idea, or opinion from the user into the "
                "feedback inbox. Use when the user reports a bug, suggests an improvement, "
                "or shares an opinion about the product. Do not use for ordinary how-to "
                "questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["bug", "idea", "opinion"],
                        "description": "bug = defect; idea = feature/suggestion; opinion = general view.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title (max ~80 chars).",
                    },
                    "body": {
                        "type": "string",
                        "description": "Clear description with relevant context.",
                    },
                },
                "required": ["kind", "title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "feedback_list",
            "description": (
                "List feedback items (bugs/ideas/opinions) from the inbox. "
                "By default excludes archived items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["open", "in_progress", "done", "archived"],
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["bug", "idea", "opinion"],
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 20,
                    },
                    "include_archived": {
                        "type": "boolean",
                        "default": False,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "feedback_get",
            "description": "Fetch one feedback item by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                },
                "required": ["id"],
            },
        },
    },
]


def help_feedback_tool_specs() -> list[dict[str, Any]]:
    return list(FEEDBACK_TOOL_SPECS)


def _compact(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def run_feedback_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    help_session_id: str | None = None,
    view_path: str | None = None,
) -> str:
    if name == "feedback_create":
        kind = str(arguments.get("kind", "")).strip()
        title = str(arguments.get("title", "")).strip()
        body = str(arguments.get("body", "")).strip()
        if kind not in {"bug", "idea", "opinion"}:
            return "kind must be bug, idea, or opinion"
        if not title:
            return "title is required"
        row = await create_feedback_item(
            session,
            FeedbackItemCreate(
                kind=kind,  # type: ignore[arg-type]
                title=title[:255],
                body=body,
                source="help",
                session_id=help_session_id,
                view_path=view_path,
            ),
        )
        return _compact({"ok": True, "item": serialize_feedback_item(row).model_dump()})

    if name == "feedback_list":
        status_raw = arguments.get("status")
        kind_raw = arguments.get("kind")
        status: FeedbackStatus | None = None
        kind: FeedbackKind | None = None
        if isinstance(status_raw, str) and status_raw.strip():
            status = status_raw.strip()  # type: ignore[assignment]
            if status not in {"open", "in_progress", "done", "archived"}:
                return "invalid status"
        if isinstance(kind_raw, str) and kind_raw.strip():
            kind = kind_raw.strip()  # type: ignore[assignment]
            if kind not in {"bug", "idea", "opinion"}:
                return "invalid kind"
        limit = int(arguments.get("limit") or 20)
        include_archived = bool(arguments.get("include_archived"))
        rows = await list_feedback_items(
            session,
            status=status,
            kind=kind,
            include_archived=include_archived or status == "archived",
            limit=max(1, min(limit, 50)),
        )
        items = [serialize_feedback_item(row).model_dump() for row in rows]
        return _compact({"count": len(items), "items": items})

    if name == "feedback_get":
        try:
            item_id = int(arguments.get("id"))
        except (TypeError, ValueError):
            return "id must be an integer"
        from app.database.models import FeedbackItem

        row = await session.get(FeedbackItem, item_id)
        if row is None:
            return f"Feedback item not found: {item_id}"
        return _compact(serialize_feedback_item(row).model_dump())

    raise ValueError(f"Unknown feedback tool: {name}")
