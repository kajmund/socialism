"""Owner-backed ClassificationDefinition reads and writes."""

from __future__ import annotations

from typing import Any

from app.services.clause_ssr.keys import classification_key
from app.services.clause_ssr.labels import CLASSIFICATION
from app.services.clause_ssr.types import LEVELS, ClassificationDefinition, ClassificationLevel
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.labels import scope_label
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_graph import (
    apply_batch,
    make_node,
    props_of,
    read_nodes,
)

PAGE_LIMIT = 1000


def _str(props: dict[str, Any], name: str) -> str:
    return str(props.get(name) or "")


def _int(props: dict[str, Any], name: str, default: int = 0) -> int:
    value = props.get(name)
    return int(value) if isinstance(value, (int, float, str)) and str(value) else default


def _from_props(key: str, props: dict[str, Any]) -> ClassificationDefinition:
    level = _str(props, "level") or "clause"
    if level not in LEVELS:
        raise ValueError(f"corrupt classification level: {level}")
    return ClassificationDefinition(
        id=key, slug=_str(props, "slug"), version=_int(props, "version", 1),
        question=_str(props, "question"), level=level,  # type: ignore[arg-type]
        category=_str(props, "category"), active=bool(props.get("active")),
        scope_key=_str(props, "scope_key"),
    )


async def get(client: OwnerClient, classification_id: str) -> ClassificationDefinition:
    response = await read_nodes(client, [(CLASSIFICATION, classification_id)])
    props = props_of(response, CLASSIFICATION, classification_id)
    if props is None:
        raise KeyError(f"unknown classification {classification_id}")
    return _from_props(classification_id, props)


async def list_classifications(
    client: OwnerClient, *, customer_id: int | None, active_only: bool = True,
) -> list[ClassificationDefinition]:
    from app.services.overgraph.labels import visible_scope_keys

    items: list[ClassificationDefinition] = []
    for scope_key in visible_scope_keys(customer_id):
        cursor: int | None = None
        while True:
            page = await client.query_nodes(
                CLASSIFICATION, props={"scope_key": scope_key},
                limit=PAGE_LIMIT, after=cursor,
            )
            for row in page["nodes"]:
                items.append(_from_props(str(row["key"]), dict(row.get("props") or {})))
            cursor = page.get("next_cursor")
            if cursor is None:
                break
    if active_only:
        items = [item for item in items if item.active]
    items.sort(key=lambda item: (item.category, item.slug, item.version))
    return items


async def _active_for_slug(
    client: OwnerClient, scope_key: str, slug: str,
) -> ClassificationDefinition | None:
    cursor: int | None = None
    found: list[ClassificationDefinition] = []
    while True:
        page = await client.query_nodes(
            CLASSIFICATION, props={"scope_key": scope_key, "slug": slug},
            limit=PAGE_LIMIT, after=cursor,
        )
        for row in page["nodes"]:
            item = _from_props(str(row["key"]), dict(row.get("props") or {}))
            if item.active:
                found.append(item)
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    found.sort(key=lambda item: item.version, reverse=True)
    return found[0] if found else None


def _props(
    *, slug: str, version: int, question: str, level: str,
    category: str, active: bool, scope_key: str,
) -> dict[str, Any]:
    return {
        "scope_key": scope_key, "slug": slug, "version": version,
        "question": question, "level": level, "category": category,
        "active": active,
    }


async def _write(
    client: OwnerClient, *, key: str, scope: KnowledgeTenantScope,
    props: dict[str, Any],
) -> None:
    await apply_batch(
        client, "clause:classification",
        nodes=[make_node([CLASSIFICATION, scope_label(scope.scope_key)], key, props)],
        edges=[],
    )


async def upsert(
    client: OwnerClient,
    *,
    scope: KnowledgeTenantScope,
    slug: str,
    question: str,
    category: str,
    level: ClassificationLevel = "clause",
    version: int | None = None,
) -> ClassificationDefinition:
    if level not in LEVELS:
        raise ValueError(f"unknown classification level: {level}")
    slug, question, category = slug.strip(), question.strip(), category.strip()
    if not slug or not question or not category:
        raise ValueError("slug, question, and category are required")
    current = await _active_for_slug(client, scope.scope_key, slug)
    if current is not None and current.question == question and current.level == level:
        if current.category == category:
            return current
    next_version = version or ((current.version + 1) if current is not None else 1)
    if current is not None and current.version != next_version:
        await _write(client, key=current.id, scope=scope, props=_props(
            slug=current.slug, version=current.version, question=current.question,
            level=current.level, category=current.category, active=False,
            scope_key=scope.scope_key,
        ))
    key = classification_key(scope.scope_key, slug, next_version)
    props = _props(
        slug=slug, version=next_version, question=question, level=level,
        category=category, active=True, scope_key=scope.scope_key,
    )
    await _write(client, key=key, scope=scope, props=props)
    return _from_props(key, props)


async def set_active(
    client: OwnerClient,
    classification: ClassificationDefinition,
    *,
    scope: KnowledgeTenantScope,
    active: bool,
) -> ClassificationDefinition:
    if classification.scope_key != scope.scope_key:
        raise PermissionError("classification is outside the caller tenant")
    props = _props(
        slug=classification.slug, version=classification.version,
        question=classification.question, level=classification.level,
        category=classification.category, active=active, scope_key=scope.scope_key,
    )
    await _write(client, key=classification.id, scope=scope, props=props)
    return _from_props(classification.id, props)
