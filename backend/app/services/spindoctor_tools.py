"""Read-only run tools Spinndoktor may call during a chat turn."""

from __future__ import annotations

import json
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.report.bundles import RunBundle
from app.services.report.metrics import compute_report_metrics
from app.services.report.persona_bio import build_agent_bio_by_index, persona_profile_line
from app.services.report.tick_report import extract_interview_qa
from app.services.spindoctor_context import load_spindoctor_source

ReactionKind = Literal["post", "comment", "any"]

SPINDOCTOR_TOOL_NAMES = frozenset(
    {
        "get_test_message",
        "get_run",
        "search_reactions",
        "list_interviews",
        "list_actors",
        "get_citizen",
    }
)

_TEXT_CHARS = 400
_MAX_SEARCH = 40
_DEFAULT_SEARCH = 12
_MAX_INTERVIEWS = 30
_DEFAULT_INTERVIEWS = 12
_MAX_ACTORS = 10
_DEFAULT_ACTORS = 5
_MAX_CITIZEN_ITEMS = 20

SPINDOCTOR_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_test_message",
            "description": (
                "Return the test campaign message(s) injected in this run "
                "(frozen timeline text per variant). Call when the user asks "
                "what was said, how to rewrite the message, or anything that "
                "needs the actual wording."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_run",
            "description": (
                "Return run identity and activity counts: ticks, variants, "
                "posts, comments, likes, follows, and action histogram."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reactions",
            "description": (
                "Search posts and comments from the simulation. Empty query "
                "lists the latest items. Use to quote reactions or find how "
                "people talked about a topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Case-insensitive substring. Empty = no text filter.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["post", "comment", "any"],
                        "description": "Default any.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 40,
                        "default": 12,
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_interviews",
            "description": (
                "List planned interview question/answer pairs from the run."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 30,
                        "default": 12,
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_actors",
            "description": (
                "List the most visible voices (likes + a sample line)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_citizen",
            "description": (
                "Look up one simulated citizen by name and return profile "
                "plus their posts and comments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name or part of the name.",
                    },
                },
                "required": ["name"],
            },
        },
    },
]


def spindoctor_tool_specs() -> list[dict[str, Any]]:
    return list(SPINDOCTOR_TOOL_SPECS)


def _compact(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _item_text(item: dict[str, Any]) -> str:
    return str(item.get("content") or item.get("text") or "").strip()


def _likes(item: dict[str, Any]) -> int:
    for key in ("num_likes", "likes", "like_count"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _user_id(item: dict[str, Any]) -> int | None:
    for key in ("user_id", "agent_id", "author_id"):
        value = item.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _agent_name(bundle: RunBundle, user_id: int | None) -> str:
    if user_id is None:
        return "—"
    for agent in bundle.agents:
        if agent.get("index") == user_id:
            return str(agent.get("member_name") or agent.get("name") or f"agent {user_id}")
    return f"agent {user_id}"


def _clamp(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _get_test_message(bundles: list[RunBundle]) -> str:
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        texts = [text.strip() for text in bundle.injection_texts if text.strip()]
        rows.append(
            {
                "label": bundle.label,
                "variant_id": bundle.variant_id or "main",
                "messages": texts,
            }
        )
    return _compact({"bundles": rows})


def _get_run(bundles: list[RunBundle]) -> str:
    metrics = compute_report_metrics(bundles)
    rows: list[dict[str, Any]] = []
    for bundle, bundle_metrics in zip(bundles, metrics.bundles, strict=True):
        rows.append(
            {
                "label": bundle.label,
                "run_id": bundle.run_id,
                "run_name": bundle.run_name,
                "attempt_id": bundle.attempt_id,
                "variant_id": bundle.variant_id or "main",
                "ticks_run": bundle.ticks_run,
                "engine": bundle.engine,
                "posts": bundle_metrics.post_count,
                "comments": bundle_metrics.comment_count,
                "likes": bundle_metrics.likes_total,
                "injection_likes": bundle_metrics.injection_likes,
                "follows": bundle_metrics.follow_edges,
                "action_histogram": bundle_metrics.action_histogram,
            }
        )
    return _compact({"bundles": rows})


def _search_reactions(
    bundles: list[RunBundle],
    arguments: dict[str, Any],
) -> str:
    query = str(arguments.get("query") or "").strip().casefold()
    kind_raw = str(arguments.get("kind") or "any").strip()
    kind: ReactionKind = kind_raw if kind_raw in {"post", "comment", "any"} else "any"
    limit = _clamp(arguments.get("limit"), default=_DEFAULT_SEARCH, lo=1, hi=_MAX_SEARCH)
    offset = _clamp(arguments.get("offset"), default=0, lo=0, hi=10_000)

    hits: list[dict[str, Any]] = []
    for bundle in bundles:
        pairs: list[tuple[str, dict[str, Any]]] = []
        if kind in {"post", "any"}:
            pairs.extend(("post", item) for item in bundle.posts)
        if kind in {"comment", "any"}:
            pairs.extend(("comment", item) for item in bundle.comments)
        for item_kind, item in pairs:
            text = _item_text(item)
            if not text:
                continue
            if query and query not in text.casefold():
                continue
            uid = _user_id(item)
            hits.append(
                {
                    "label": bundle.label,
                    "kind": item_kind,
                    "author": _agent_name(bundle, uid),
                    "likes": _likes(item),
                    "text": _clip(text, _TEXT_CHARS),
                }
            )
    page = hits[offset : offset + limit]
    return _compact({"total": len(hits), "offset": offset, "items": page})


def _list_interviews(bundles: list[RunBundle], arguments: dict[str, Any]) -> str:
    limit = _clamp(
        arguments.get("limit"), default=_DEFAULT_INTERVIEWS, lo=1, hi=_MAX_INTERVIEWS
    )
    offset = _clamp(arguments.get("offset"), default=0, lo=0, hi=10_000)
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        for qa in extract_interview_qa(bundle):
            rows.append(
                {
                    "label": bundle.label,
                    "agent": qa.agent_name,
                    "day": qa.day,
                    "question": _clip(qa.question, 200),
                    "answer": _clip(qa.answer, _TEXT_CHARS),
                }
            )
    page = rows[offset : offset + limit]
    return _compact({"total": len(rows), "offset": offset, "items": page})


def _list_actors(bundles: list[RunBundle], arguments: dict[str, Any]) -> str:
    limit = _clamp(arguments.get("limit"), default=_DEFAULT_ACTORS, lo=1, hi=_MAX_ACTORS)
    metrics = compute_report_metrics(bundles)
    actors = []
    for actor in metrics.aggregate.top_actors[:limit]:
        actors.append(
            {
                "name": actor.get("name"),
                "likes_total": actor.get("likes_total"),
                "items": actor.get("items"),
                "sample": _clip(str(actor.get("sample") or ""), _TEXT_CHARS),
            }
        )
    return _compact({"actors": actors})


def _citizen_items(bundle: RunBundle, user_id: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for kind, rows in (("post", bundle.posts), ("comment", bundle.comments)):
        for row in rows:
            if _user_id(row) != user_id:
                continue
            text = _item_text(row)
            if not text:
                continue
            items.append(
                {
                    "kind": kind,
                    "likes": _likes(row),
                    "text": _clip(text, _TEXT_CHARS),
                }
            )
            if len(items) >= _MAX_CITIZEN_ITEMS:
                return items
    return items


def _get_citizen(bundles: list[RunBundle], arguments: dict[str, Any]) -> str:
    needle = str(arguments.get("name") or "").strip().casefold()
    if not needle:
        return "name is required"
    matches: list[dict[str, Any]] = []
    for bundle in bundles:
        bios = build_agent_bio_by_index(bundle)
        seen: set[int] = set()
        for agent in bundle.agents:
            if str(agent.get("role") or "") == "injector":
                continue
            try:
                idx = int(agent.get("index"))
            except (TypeError, ValueError):
                continue
            if idx in seen:
                continue
            name = str(agent.get("member_name") or agent.get("name") or "").strip()
            if not name or needle not in name.casefold():
                continue
            seen.add(idx)
            bio = bios.get(idx) or {}
            matches.append(
                {
                    "label": bundle.label,
                    "name": name,
                    "profile": persona_profile_line(bio, locale="sv") or None,
                    "items": _citizen_items(bundle, idx),
                }
            )
    if not matches:
        return _compact({"matches": [], "note": f"No citizen matched {needle!r}"})
    return _compact({"matches": matches})


def run_spindoctor_tool_on_bundles(
    name: str,
    arguments: dict[str, Any],
    bundles: list[RunBundle],
) -> str:
    if name not in SPINDOCTOR_TOOL_NAMES:
        raise ValueError(f"Unknown Spinndoktor tool: {name}")
    if name == "get_test_message":
        return _get_test_message(bundles)
    if name == "get_run":
        return _get_run(bundles)
    if name == "search_reactions":
        return _search_reactions(bundles, arguments)
    if name == "list_interviews":
        return _list_interviews(bundles, arguments)
    if name == "list_actors":
        return _list_actors(bundles, arguments)
    return _get_citizen(bundles, arguments)


async def run_spindoctor_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    report_id: str,
) -> str:
    if name not in SPINDOCTOR_TOOL_NAMES:
        raise ValueError(f"Unknown Spinndoktor tool: {name}")
    _report, bundles = await load_spindoctor_source(session, report_id=report_id)
    return run_spindoctor_tool_on_bundles(name, arguments, bundles)
