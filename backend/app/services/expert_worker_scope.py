"""Bind worker reads to section and anchor ids from the document and prior tool results."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

def cited_scope_ids(episode: object | None) -> set[str]:
    messages = getattr(episode, "messages", ()) or ()
    found: set[str] = set()
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        found.update(_json_strings(message.get("content")))
    return found


async def allowed_scope_ids(
    episode: object | None, source_ids: Sequence[str]
) -> dict[str, set[str]]:
    cited = cited_scope_ids(episode)
    navigation, job_session_factory = _document_imports()
    factory = job_session_factory()
    allowed: dict[str, set[str]] = {}
    async with factory() as session:
        for source_id in dict.fromkeys(source_ids):
            index = await navigation.source_scope_index(session, source_id)
            allowed[source_id] = set(index.ids) & cited
        await session.rollback()
    return allowed


async def load_source_scope(source_id: str):
    navigation, job_session_factory = _document_imports()
    factory = job_session_factory()
    async with factory() as session:
        index = await navigation.source_scope_index(session, source_id)
        await session.rollback()
    return index


def read_section_allowed(
    section: object, scope_ids: Sequence[str], titles: Mapping[str, str]
) -> bool:
    if not isinstance(section, str) or not section:
        return False
    if section in scope_ids:
        return True
    needle = _collapsed(section)
    matches = [
        section_id
        for section_id, title in titles.items()
        if section_id in scope_ids and _collapsed(title) == needle
    ]
    return len(matches) == 1


def confine_search_payload(
    payload: str,
    allowed: frozenset[str],
    passages: Sequence[tuple[str, str | None, str]],
) -> str:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return _blocked()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return _blocked()
    scoped = [
        passage
        for passage in passages
        if passage[0] in allowed or (passage[1] is not None and passage[1] in allowed)
    ]
    data["items"] = [item for item in data["items"] if _keep_item(item, allowed, scoped)]
    data.pop("text", None)
    return json.dumps(data, ensure_ascii=False)


def _keep_item(
    item: object,
    allowed: frozenset[str],
    passages: Sequence[tuple[str, str | None, str]],
) -> bool:
    if not isinstance(item, dict):
        return False
    identities = _item_ids(item)
    if identities:
        in_scope = set(allowed)
        in_scope.update(unit_id for unit_id, _section_id, _text in passages)
        return bool(identities & in_scope)
    excerpt = _excerpt(item)
    needle = _collapsed(excerpt)
    if not needle:
        return False
    return any(needle in _collapsed(text) for _unit_id, _section_id, text in passages)


def _item_ids(item: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for key in ("section_id", "text_unit_id", "anchor_id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            found.add(value)
    for key in ("snapshot", "anchor", "metadata"):
        nested = item.get(key)
        if isinstance(nested, dict):
            found.update(_item_ids(nested))
    listed = item.get("text_unit_ids")
    if isinstance(listed, list):
        found.update(entry for entry in listed if isinstance(entry, str) and entry)
    return found


def _excerpt(item: dict[str, Any]) -> str:
    for key in ("excerpt", "text", "quote"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    snapshot = item.get("snapshot")
    if isinstance(snapshot, dict):
        return _excerpt(snapshot)
    return ""


def _json_strings(value: object) -> set[str]:
    if isinstance(value, str):
        if not value:
            return set()
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {value}
        return _json_strings(parsed)
    if isinstance(value, dict):
        found: set[str] = set()
        for item in value.values():
            found.update(_json_strings(item))
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found.update(_json_strings(item))
        return found
    return set()


def _collapsed(text: str) -> str:
    from app.services.document_navigation import collapsed

    return collapsed(text)


def _document_imports():
    # workspace.service imports the module registry, which is still loading when
    # spawn is imported from expert chat. jobs → research is the same cycle.
    from app.services import document_navigation
    from app.services.jobs import job_session_factory

    return document_navigation, job_session_factory


def _blocked() -> str:
    return json.dumps({"ok": False, "error": "scope_outside_document"}, ensure_ascii=False)
